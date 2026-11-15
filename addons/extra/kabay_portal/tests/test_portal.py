from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.addons.kabay_portal.controllers import portal as portal_controller


@tagged("post_install", "-at_install")
class TestKabayPortalAccess(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.condo = cls.env["kabay.condominium"].create({
            "name": "Portal QA Condo", "code": "PORTAL-QA", "company_id": cls.company.id,
        })
        cls.building = cls.env["kabay.building"].create({
            "name": "Portal QA Torre", "code": "PORTAL-QA-A", "condominium_id": cls.condo.id,
        })
        cls.apartment = cls.env["kabay.apartment"].create({
            "name": "QA-101", "code": "QA-101", "building_id": cls.building.id,
        })
        cls.other_apartment = cls.env["kabay.apartment"].create({
            "name": "QA-102", "code": "QA-102", "building_id": cls.building.id,
        })
        cls.partner = cls.env["res.partner"].create({"name": "Portal QA Resident"})
        cls.other_partner = cls.env["res.partner"].create({"name": "Portal QA Other"})
        today = fields.Date.context_today(cls.env.user)
        cls.env["kabay.apartment.relation"].create({
            "partner_id": cls.partner.id, "apartment_id": cls.apartment.id, "role": "owner",
            "date_start": today - timedelta(days=5), "state": "confirmed",
        })
        cls.env["kabay.apartment.relation"].create({
            "partner_id": cls.other_partner.id, "apartment_id": cls.other_apartment.id, "role": "tenant",
            "date_start": today - timedelta(days=5), "state": "confirmed",
        })
        cls.portal_user = cls.env["res.users"].create({
            "name": "Portal QA User", "login": "kabay-portal-qa", "partner_id": cls.partner.id,
            "company_id": cls.company.id, "company_ids": [Command.set([cls.company.id])],
            "group_ids": [Command.set([cls.env.ref("kabay_deposits.group_kabay_deposit_resident").id])],
        })

    def test_resident_acl_is_scoped_to_current_relation(self):
        own = self.env["kabay.apartment"].with_user(self.portal_user).search([])
        self.assertIn(self.apartment, own)
        self.assertNotIn(self.other_apartment, own)
        with self.assertRaises(AccessError):
            self.env["kabay.apartment"].with_user(self.portal_user).browse(self.other_apartment.id).check_access("read")

    def test_portal_account_move_access_is_read_only(self):
        account_moves = self.env["account.move"].with_user(self.portal_user)
        # Odoo grants Portal users read access and applies its native
        # "Portal Personal Account Invoices" record rule to scope invoices.
        self.assertTrue(account_moves.has_access("read"))
        self.assertFalse(account_moves.has_access("write"))
        self.assertFalse(account_moves.has_access("create"))
        self.assertFalse(account_moves.has_access("unlink"))


@tagged("post_install", "-at_install")
class TestKabayPortalRoutes(HttpCase):
    def test_profile_does_not_reflect_internal_exception_details(self):
        partner = Mock()
        partner.write.side_effect = RuntimeError("private SQL diagnostic")
        user = Mock()
        user.partner_id = partner
        user.has_group.side_effect = lambda group: group == "kabay_deposits.group_kabay_deposit_resident"
        fake_request = SimpleNamespace(
            env=SimpleNamespace(user=user, _=lambda message: message),
            httprequest=SimpleNamespace(method="POST"),
            render=Mock(return_value="rendered"),
        )
        with patch.object(portal_controller, "request", fake_request), patch.object(
            portal_controller, "_", lambda message: message,
        ):
            result = portal_controller.KabayResidentPortal().kabay_profile(name="Test", email="bad")
        context = fake_request.render.call_args.args[1]
        self.assertEqual(result.status_code, 200)
        self.assertNotIn("private SQL diagnostic", context["error"])
        self.assertIn("No se pudieron guardar", context["error"])

    def test_resident_dashboard_units_and_foreign_unit(self):
        company = self.env.company
        condo = self.env["kabay.condominium"].create({"name": "Portal HTTP Condo", "code": "P-HTTP", "company_id": company.id})
        building = self.env["kabay.building"].create({"name": "Portal HTTP Torre", "code": "P-HTTP-A", "condominium_id": condo.id})
        unit = self.env["kabay.apartment"].create({"name": "HTTP-101", "code": "HTTP-101", "building_id": building.id})
        partner = self.env["res.partner"].create({"name": "Portal HTTP Resident"})
        stranger = self.env["res.partner"].create({"name": "Portal HTTP Stranger"})
        for resident, apartment in ((partner, unit), (stranger, self.env["kabay.apartment"].create({"name": "HTTP-102", "code": "HTTP-102", "building_id": building.id}))):
            relation = self.env["kabay.apartment.relation"].create({
                "partner_id": resident.id, "apartment_id": apartment.id, "role": "owner",
                "date_start": fields.Date.today(),
            })
            relation.action_confirm()
        user = self.env["res.users"].create({
            "name": partner.name, "login": "kabay-portal-http", "password": "portal-http-password",
            "partner_id": partner.id, "company_id": company.id, "company_ids": [Command.set([company.id])],
            "group_ids": [Command.set([self.env.ref("kabay_deposits.group_kabay_deposit_resident").id])],
        })
        self.authenticate(user.login, "portal-http-password")
        csrf_missing = self.url_open("/my/kabay/profile", data={"name": "CSRF forged name"})
        self.assertEqual(csrf_missing.status_code, 400)
        self.assertEqual(partner.name, "Portal HTTP Resident")
        portal_home = self.url_open("/my")
        self.assertEqual(portal_home.status_code, 200)
        self.assertIn(b"TU COMUNIDAD EN UN SOLO LUGAR", portal_home.content)
        dashboard = self.url_open("/my/kabay")
        units = self.url_open("/my/kabay/units")
        detail = self.url_open("/my/kabay/units/%s" % unit.id)
        foreign = self.url_open("/my/kabay/units/%s" % apartment.id)
        invoices = self.url_open("/my/kabay/invoices")
        financing = self.url_open("/my/kabay/financing")
        profile = self.url_open("/my/kabay/profile")
        deposits = self.url_open("/my/kabay/deposits")
        deposit_form = self.url_open("/my/kabay/deposits/new")
        notices = self.url_open("/my/kabay/notices")
        tickets = self.url_open("/my/kabay/tickets")
        ticket_form = self.url_open("/my/kabay/tickets/new")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"Portal HTTP Resident", dashboard.content)
        self.assertEqual(units.status_code, 200)
        self.assertIn(b"HTTP-101", units.content)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(foreign.status_code, 404)
        for response in (invoices, financing, profile, deposits, deposit_form, notices, tickets, ticket_form):
            self.assertEqual(response.status_code, 200)
        self.assertIn(b"Mis dep\xc3\xb3sitos declarados", deposits.content)
