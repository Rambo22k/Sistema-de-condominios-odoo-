import base64
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.addons.kabay_helpdesk.controllers.portal import _read_portal_uploads


@tagged("post_install", "-at_install")
class TestKabayHelpdesk(TransactionCase):
    def test_portal_upload_read_is_bounded_per_file(self):
        upload = SimpleNamespace(filename="large.pdf", stream=BytesIO(b"12345"))
        with self.assertRaises(ValidationError):
            _read_portal_uploads([upload], 1, max_file_size=4, max_total_size=8)

    def test_portal_upload_read_limits_files_per_request(self):
        uploads = [SimpleNamespace(filename=f"{n}.pdf", stream=BytesIO(b"x")) for n in range(3)]
        with self.assertRaises(ValidationError):
            _read_portal_uploads(uploads, 1, max_file_size=4, max_files=2, max_total_size=8)

    def test_portal_upload_read_limits_aggregate_size(self):
        uploads = [SimpleNamespace(filename=f"{n}.pdf", stream=BytesIO(b"1234")) for n in range(2)]
        with self.assertRaises(ValidationError):
            _read_portal_uploads(uploads, 1, max_file_size=4, max_files=2, max_total_size=7)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env["res.company"].create({"name": "Kabay Helpdesk Otra"})
        cls.condo = cls.env["kabay.condominium"].create({
            "name": "Condominio Helpdesk", "code": "HLP-1", "company_id": cls.company.id,
        })
        cls.building = cls.env["kabay.building"].create({
            "name": "Torre Helpdesk", "code": "HLP-A", "condominium_id": cls.condo.id,
        })
        cls.apartment = cls.env["kabay.apartment"].create({
            "name": "H-101", "code": "H-101", "building_id": cls.building.id,
        })
        cls.other_condo = cls.env["kabay.condominium"].create({
            "name": "Condominio Externo Helpdesk", "code": "HLP-EXT", "company_id": cls.other_company.id,
        })
        cls.other_building = cls.env["kabay.building"].create({
            "name": "Torre Externa", "code": "HLP-EXT-A", "condominium_id": cls.other_condo.id,
        })
        cls.other_apartment = cls.env["kabay.apartment"].create({
            "name": "X-101", "code": "X-101", "building_id": cls.other_building.id,
        })
        cls.partner = cls.env["res.partner"].create({"name": "Residente Helpdesk"})
        cls.other_partner = cls.env["res.partner"].create({"name": "Otro Residente Helpdesk"})
        cls.relation = cls.env["kabay.apartment.relation"].create({
            "partner_id": cls.partner.id, "apartment_id": cls.apartment.id, "role": "tenant",
            "date_start": fields.Date.today(),
        })
        cls.relation.action_confirm()
        cls.other_relation = cls.env["kabay.apartment.relation"].create({
            "partner_id": cls.other_partner.id, "apartment_id": cls.apartment.id, "role": "authorized_resident",
            "date_start": fields.Date.today(),
        })
        cls.other_relation.action_confirm()
        cls.team = cls.env["helpdesk.team"].search([
            ("company_id", "=", cls.company.id), ("kabay_resident_team", "=", True),
        ], limit=1)
        cls.category = cls.env.ref("kabay_helpdesk.category_maintenance")
        cls.portal_user = cls._make_user("portal", [cls.env.ref("base.group_portal")], cls.partner)
        cls.other_portal_user = cls._make_user("portal-other", [cls.env.ref("base.group_portal")], cls.other_partner)
        cls.reception_user = cls._make_user("reception", [cls.env.ref("kabay_base.group_kabay_reception")])
        cls.maintenance_user = cls._make_user("maintenance", [cls.env.ref("kabay_base.group_kabay_maintenance")])
        cls.management_user = cls._make_user("management", [cls.env.ref("kabay_base.group_kabay_management")])
        cls.finance_user = cls._make_user("finance", [cls.env.ref("kabay_base.group_kabay_finance")])
        cls.manager_user = cls._make_user("manager", [cls.env.ref("kabay_base.group_kabay_manager")])
        cls.team.write({"member_ids": [(4, cls.maintenance_user.id), (4, cls.reception_user.id)]})

    @classmethod
    def _make_user(cls, suffix, groups, partner=None):
        base = cls.env.ref("base.group_user") if any(group == cls.env.ref("base.group_user") for group in groups) else None
        group_ids = [group.id for group in groups]
        if base:
            group_ids.append(base.id)
        return cls.env["res.users"].create({
            "name": "Helpdesk " + suffix, "login": "kabay-helpdesk-" + suffix,
            "partner_id": partner.id if partner else cls.env["res.partner"].create({"name": "Helpdesk " + suffix + " Partner"}).id,
            "company_id": cls.company.id, "company_ids": [(6, 0, [cls.company.id])],
            "group_ids": [(6, 0, group_ids)],
        })

    def _ticket(self, partner=None, apartment=None, **extra):
        vals = {
            "name": "Solicitud de prueba", "description": "<p>Descripción de prueba</p>",
            "partner_id": (partner or self.partner).id, "team_id": self.team.id,
            "stage_id": self.team.stage_ids.filtered(lambda stage: stage.kabay_state == "new")[:1].id,
            "kabay_apartment_id": (apartment or self.apartment).id,
            "kabay_relation_id": self.relation.id if (partner or self.partner) == self.partner else self.other_relation.id,
            "kabay_category_id": self.category.id,
        }
        vals.update(extra)
        return self.env["helpdesk.ticket"].create(vals)

    def _portal_ticket(self, **extra):
        values = {
            "name": "Reporte Portal", "description": "Descripción Portal",
            "kabay_apartment_id": self.apartment.id, "kabay_category_id": self.category.id,
        }
        values.update(extra)
        return self.env["helpdesk.ticket"].with_user(self.portal_user).create(values)

    def test_01_creation_keeps_residential_links_and_company(self):
        ticket = self._portal_ticket()
        self.assertEqual(ticket.partner_id, self.partner)
        self.assertEqual(ticket.kabay_apartment_id, self.apartment)
        self.assertEqual(ticket.kabay_building_id, self.building)
        self.assertEqual(ticket.kabay_condominium_id, self.condo)
        self.assertEqual(ticket.company_id, self.company)
        self.assertEqual(ticket.kabay_relation_id, self.relation)

    def test_02_helpdesk_generates_unique_reference(self):
        first, second = self._portal_ticket(), self._portal_ticket(name="Otra solicitud")
        self.assertTrue(first.ticket_ref)
        self.assertNotEqual(first.ticket_ref, second.ticket_ref)

    def test_03_valid_apartment_is_accepted(self):
        self.assertEqual(self._portal_ticket().kabay_apartment_id, self.apartment)

    def test_04_expired_relationship_is_rejected(self):
        expired = self.env["kabay.apartment.relation"].create({
            "partner_id": self.partner.id, "apartment_id": self.env["kabay.apartment"].create({
                "name": "H-102", "code": "H-102", "building_id": self.building.id,
            }).id,
            "role": "tenant", "date_start": "2020-01-01", "date_end": "2020-02-01",
        })
        expired.action_confirm()
        with self.assertRaises(AccessError):
            self._portal_ticket(kabay_apartment_id=expired.apartment_id.id)

    def test_05_apartment_of_another_resident_is_rejected(self):
        with self.assertRaises(AccessError):
            self._portal_ticket(kabay_apartment_id=self.other_apartment.id)

    def test_06_apartment_in_another_company_is_rejected(self):
        relation = self.env["kabay.apartment.relation"].create({
            "partner_id": self.partner.id, "apartment_id": self.other_apartment.id, "role": "tenant",
            "date_start": fields.Date.today(),
        })
        relation.action_confirm()
        with self.assertRaises(AccessError):
            self._portal_ticket(kabay_apartment_id=self.other_apartment.id)

    def test_07_inactive_category_is_rejected(self):
        self.category.with_user(self.env.user).write({"active": False})
        with self.assertRaises(ValidationError):
            self._portal_ticket()
        self.category.write({"active": True})

    def test_08_all_priorities_are_accepted_without_permission_change(self):
        for priority in ("0", "1", "2", "3"):
            self.assertEqual(self._portal_ticket(priority=priority).priority, priority)
        self.assertFalse(self.portal_user.has_group("helpdesk.group_helpdesk_manager"))

    def test_09_invalid_priority_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._portal_ticket(priority="4")

    def test_10_valid_state_transition_is_allowed(self):
        ticket = self._ticket()
        ticket.with_user(self.reception_user).action_kabay_set_state("review")
        self.assertEqual(ticket.kabay_state, "review")

    def test_11_invalid_state_transition_is_rejected(self):
        ticket = self._ticket()
        with self.assertRaises(UserError):
            ticket.with_user(self.reception_user).action_kabay_set_state("closed")

    def test_12_staff_can_assign_responsible_user(self):
        ticket = self._ticket()
        ticket.with_user(self.reception_user).write({"user_id": self.maintenance_user.id})
        self.assertEqual(ticket.user_id, self.maintenance_user)

    def test_13_resident_message_is_public(self):
        ticket = self._portal_ticket()
        ticket.with_user(self.portal_user).message_post(body="Respuesta residente")
        self.assertIn("Respuesta residente", " ".join(ticket.website_message_ids.mapped("body")))

    def test_14_internal_note_is_not_in_public_message_set(self):
        ticket = self._ticket()
        ticket.with_user(self.reception_user).message_post(
            body="Nota privada", subtype_xmlid="mail.mt_note", message_type="comment",
        )
        self.assertNotIn("Nota privada", " ".join(ticket._kabay_public_messages().mapped("body")))

    def test_15_portal_user_sees_only_own_ticket(self):
        own = self._portal_ticket()
        self._ticket(partner=self.other_partner, apartment=self.apartment)
        self.assertEqual(self.env["helpdesk.ticket"].with_user(self.portal_user).search_count([
            ("kabay_apartment_id", "!=", False),
        ]), 1)
        self.assertTrue(own.with_user(self.portal_user).exists())

    def test_16_portal_user_cannot_read_other_contact_ticket(self):
        other = self._ticket(partner=self.other_partner, apartment=self.apartment)
        with self.assertRaises(AccessError):
            other.with_user(self.portal_user).read(["name"])

    def test_17_attachment_type_and_size_validation(self):
        ticket = self._portal_ticket()
        with self.assertRaises(ValidationError):
            self.env["kabay.helpdesk.attachment"].with_user(self.portal_user).create({
                "ticket_id": ticket.id, "name": "payload.exe", "datas": base64.b64encode(b"x"),
            })
        with self.assertRaises(ValidationError):
            self.env["kabay.helpdesk.attachment"].with_user(self.portal_user).create({
                "ticket_id": ticket.id, "name": "large.pdf",
                "datas": base64.b64encode(b"x" * (10 * 1024 * 1024 + 1)),
            })

    def test_18_portal_cannot_read_another_tickets_attachment(self):
        ticket = self._portal_ticket()
        attachment = self.env["kabay.helpdesk.attachment"].create({
            "ticket_id": ticket.id, "name": "foto.jpg", "datas": base64.b64encode(b"image"),
        })
        with self.assertRaises(AccessError):
            attachment.with_user(self.other_portal_user).read(["name"])

    def test_19_chatter_records_creation_and_messages(self):
        ticket = self._portal_ticket()
        ticket.with_user(self.portal_user).message_post(body="Auditoría de respuesta")
        self.assertTrue(ticket.message_ids)
        self.assertTrue(ticket.message_ids.filtered(lambda message: "Auditoría de respuesta" in message.body))

    def test_20_manager_can_configure_category(self):
        category = self.env["kabay.helpdesk.category"].with_user(self.manager_user).create({"name": "Categoría especial"})
        category.write({"active": False})
        self.assertFalse(category.active)

    def test_21_reception_can_read_and_classify(self):
        ticket = self._ticket()
        as_reception = ticket.with_user(self.reception_user)
        self.assertEqual(as_reception.name, ticket.name)
        as_reception.write({"priority": "2"})
        self.assertEqual(ticket.priority, "2")

    def test_22_maintenance_can_manage_team_ticket(self):
        ticket = self._ticket()
        as_maintenance = ticket.with_user(self.maintenance_user)
        self.assertEqual(as_maintenance.name, ticket.name)
        as_maintenance.write({"priority": "2"})
        self.assertEqual(ticket.priority, "2")

    def test_23_finance_has_no_ticket_or_attachment_access(self):
        ticket = self._ticket()
        self.assertEqual(self.env["helpdesk.ticket"].with_user(self.finance_user).search_count([]), 0)
        with self.assertRaises(AccessError):
            ticket.with_user(self.finance_user).read(["name"])
        self.assertFalse(self.finance_user.has_group("helpdesk.group_helpdesk_manager"))

    def test_24_company_rule_hides_ticket_when_company_not_allowed(self):
        ticket = self._ticket()
        user = self.env["res.users"].create({
            "name": "Kabay multi-company", "login": "kabay-helpdesk-multi",
            "company_id": self.other_company.id, "company_ids": [(6, 0, [self.other_company.id])],
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id, self.env.ref("kabay_base.group_kabay_management").id])],
        })
        self.assertEqual(self.env["helpdesk.ticket"].with_user(user).search_count([("id", "=", ticket.id)]), 0)

    def test_25_ended_relation_does_not_transfer_historical_ticket(self):
        ticket = self._portal_ticket()
        self.relation.action_end()
        self.assertEqual(ticket.partner_id, self.partner)
        self.assertEqual(ticket.kabay_relation_id, self.relation)
        with self.assertRaises(AccessError):
            self._portal_ticket()

    def test_26_resolved_ticket_can_be_reopened_by_resident(self):
        ticket = self._ticket()
        ticket.with_user(self.reception_user).action_kabay_set_state("review")
        ticket.with_user(self.reception_user).action_kabay_set_state("in_progress")
        ticket.with_user(self.reception_user).action_kabay_set_state("resolved")
        ticket.with_user(self.portal_user).action_kabay_portal_reopen()
        self.assertEqual(ticket.kabay_state, "in_progress")

    def test_27_portal_cannot_change_state_or_edit_directly(self):
        ticket = self._portal_ticket()
        with self.assertRaises(AccessError):
            ticket.with_user(self.portal_user).write({"priority": "3"})
        with self.assertRaises(AccessError):
            ticket.with_user(self.portal_user).action_kabay_set_state("resolved")

    def test_28_resident_identity_is_historical_and_immutable(self):
        ticket = self._ticket()
        with self.assertRaises(AccessError):
            ticket.write({"partner_id": self.other_partner.id})
        with self.assertRaises(AccessError):
            ticket.write({"kabay_apartment_id": self.other_apartment.id})

    def test_29_native_application_views_and_categories_are_loaded(self):
        self.assertTrue(self.env.ref("kabay_helpdesk.action_kabay_helpdesk_tickets"))
        self.assertTrue(self.env.ref("kabay_helpdesk.view_kabay_helpdesk_ticket_form"))
        self.assertEqual(self.env["kabay.helpdesk.category"].search_count([]), 10)

    def test_30_new_company_gets_a_kabay_team_and_workflow(self):
        company = self.env["res.company"].create({"name": "Kabay Helpdesk Compañía Nueva"})
        team = self.env["helpdesk.team"].search([
            ("company_id", "=", company.id), ("kabay_resident_team", "=", True),
        ], limit=1)
        self.assertTrue(team)
        self.assertEqual(set(filter(None, team.stage_ids.mapped("kabay_state"))), {
            "new", "review", "assigned", "in_progress", "waiting_resident", "resolved", "closed", "cancelled",
        })


@tagged("post_install", "-at_install")
class TestKabayHelpdeskPortalRoutes(HttpCase):
    def test_31_portal_login_and_real_ticket_routes(self):
        company = self.env.company
        condo = self.env["kabay.condominium"].create({"name": "Portal Helpdesk", "code": "P-HLP", "company_id": company.id})
        building = self.env["kabay.building"].create({"name": "Portal Torre", "code": "P-HLP-A", "condominium_id": condo.id})
        apartment = self.env["kabay.apartment"].create({"name": "P-101", "code": "P-101", "building_id": building.id})
        partner = self.env["res.partner"].create({"name": "Portal Route Resident"})
        relation = self.env["kabay.apartment.relation"].create({
            "partner_id": partner.id, "apartment_id": apartment.id, "role": "owner",
            "date_start": fields.Date.today(),
        })
        relation.action_confirm()
        portal_group = self.env.ref("base.group_portal")
        user = self.env["res.users"].create({
            "name": "Portal Route User", "login": "kabay-helpdesk-route", "password": "portal-route-password",
            "partner_id": partner.id, "company_id": company.id, "company_ids": [(6, 0, [company.id])],
            "group_ids": [(6, 0, [portal_group.id])],
        })
        team = self.env["helpdesk.team"].search([("company_id", "=", company.id), ("kabay_resident_team", "=", True)], limit=1)
        category = self.env.ref("kabay_helpdesk.category_other")
        ticket = self.env["helpdesk.ticket"].with_user(user).create({
            "name": "Ruta Portal", "description": "Ticket por HttpCase",
            "kabay_apartment_id": apartment.id, "kabay_category_id": category.id,
        })
        own_file = self.env["kabay.helpdesk.attachment"].with_user(user).create({
            "ticket_id": ticket.id, "name": "evidencia.txt", "datas": base64.b64encode(b"archivo propio"),
        })
        other_partner = self.env["res.partner"].create({"name": "Resident outside Portal route"})
        other_relation = self.env["kabay.apartment.relation"].create({
            "partner_id": other_partner.id, "apartment_id": apartment.id, "role": "tenant",
            "date_start": fields.Date.today(),
        })
        other_relation.action_confirm()
        stage = team.stage_ids.filtered(lambda item: item.kabay_state == "new")[:1]
        other_ticket = self.env["helpdesk.ticket"].create({
            "name": "Privado de otra persona", "description": "No visible",
            "partner_id": other_partner.id, "team_id": team.id, "stage_id": stage.id,
            "kabay_apartment_id": apartment.id, "kabay_relation_id": other_relation.id,
            "kabay_category_id": category.id,
        })
        other_file = self.env["kabay.helpdesk.attachment"].create({
            "ticket_id": other_ticket.id, "name": "privado.txt", "datas": base64.b64encode(b"privado"),
        })
        self.authenticate(user.login, "portal-route-password")
        login_response = self.url_open("/web/login")
        home_response = self.url_open("/my")
        notices_response = self.url_open("/my/kabay/notices")
        list_response = self.url_open("/my/kabay/tickets")
        detail_response = self.url_open("/my/kabay/tickets/%s" % ticket.id)
        new_response = self.url_open("/my/kabay/tickets/new")
        file_response = self.url_open("/my/kabay/tickets/file/%s" % own_file.id)
        foreign_ticket_response = self.url_open("/my/kabay/tickets/%s" % other_ticket.id)
        foreign_file_response = self.url_open("/my/kabay/tickets/file/%s" % other_file.id)
        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(home_response.status_code, 200)
        self.assertEqual(notices_response.status_code, 200)
        self.assertEqual(new_response.status_code, 200)
        self.assertEqual(list_response.status_code, 200)
        self.assertIn(ticket.ticket_ref.encode(), list_response.content)
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn(b"Ticket por HttpCase", detail_response.content)
        self.assertEqual(file_response.status_code, 200)
        self.assertIn(b"archivo propio", file_response.content)
        self.assertEqual(foreign_ticket_response.status_code, 404)
        self.assertEqual(foreign_file_response.status_code, 404)
