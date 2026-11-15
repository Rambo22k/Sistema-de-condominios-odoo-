from base64 import b64encode
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKabayNotices(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].search([("name", "=", "Kabay RD - Desarrollo")], limit=1)
        if not cls.company:
            raise AssertionError("La empresa Kabay RD - Desarrollo debe existir.")
        cls.condominium = cls.env["kabay.condominium"].create({
            "name": "QA Avisos Central", "code": "NOTICE-QA-A", "company_id": cls.company.id,
        })
        cls.condominium2 = cls.env["kabay.condominium"].create({
            "name": "QA Avisos Secundario", "code": "NOTICE-QA-B", "company_id": cls.company.id,
        })
        cls.building = cls.env["kabay.building"].create({
            "name": "Torre Avisos A", "code": "NOTICE-QA-A1", "condominium_id": cls.condominium.id,
        })
        cls.building2 = cls.env["kabay.building"].create({
            "name": "Torre Avisos B", "code": "NOTICE-QA-B1", "condominium_id": cls.condominium2.id,
        })
        cls.apartment = cls.env["kabay.apartment"].create({
            "name": "Avisos A-101", "code": "NOTICE-QA-A101", "building_id": cls.building.id,
        })
        cls.apartment2 = cls.env["kabay.apartment"].create({
            "name": "Avisos A-102", "code": "NOTICE-QA-A102", "building_id": cls.building.id,
        })
        cls.apartment_other_condo = cls.env["kabay.apartment"].create({
            "name": "Avisos B-101", "code": "NOTICE-QA-B101", "building_id": cls.building2.id,
        })
        cls.owner = cls.env["res.partner"].create({"name": "Residente propietario avisos", "company_type": "person"})
        cls.tenant = cls.env["res.partner"].create({"name": "Residente inquilino avisos", "company_type": "person"})
        cls.authorized = cls.env["res.partner"].create({"name": "Residente autorizado avisos", "company_type": "person"})
        cls.outsider = cls.env["res.partner"].create({"name": "Residente otro condominio", "company_type": "person"})
        today = fields.Date.context_today(cls.env["kabay.notice"])
        cls.env["kabay.apartment.relation"].create([
            {"partner_id": cls.owner.id, "apartment_id": cls.apartment.id, "role": "owner", "date_start": today - timedelta(days=500), "state": "confirmed"},
            {"partner_id": cls.tenant.id, "apartment_id": cls.apartment.id, "role": "tenant", "date_start": today - timedelta(days=300), "state": "confirmed"},
            {"partner_id": cls.authorized.id, "apartment_id": cls.apartment2.id, "role": "authorized_resident", "date_start": today - timedelta(days=200), "state": "confirmed"},
            {"partner_id": cls.outsider.id, "apartment_id": cls.apartment_other_condo.id, "role": "owner", "date_start": today - timedelta(days=100), "state": "confirmed"},
        ])
        cls.admin = cls.env["res.users"].create({
            "name": "Administración QA avisos", "login": "kabay_notice_manager_test",
            "company_id": cls.company.id, "company_ids": [Command.set([cls.company.id])],
            "group_ids": [Command.set([cls.env.ref("base.group_user").id, cls.env.ref("kabay_base.group_kabay_manager").id])],
        })
        cls.management = cls.env["res.users"].create({
            "name": "Gerencia QA avisos", "login": "kabay_notice_management_test",
            "company_id": cls.company.id, "company_ids": [Command.set([cls.company.id])],
            "group_ids": [Command.set([cls.env.ref("base.group_user").id, cls.env.ref("kabay_base.group_kabay_management").id])],
        })
        cls.finance = cls.env["res.users"].create({
            "name": "Finanzas QA avisos", "login": "kabay_notice_finance_test",
            "company_id": cls.company.id, "company_ids": [Command.set([cls.company.id])],
            "group_ids": [Command.set([cls.env.ref("base.group_user").id, cls.env.ref("kabay_base.group_kabay_finance").id])],
        })
        cls.reception = cls.env["res.users"].create({
            "name": "Recepción QA avisos", "login": "kabay_notice_reception_test",
            "company_id": cls.company.id, "company_ids": [Command.set([cls.company.id])],
            "group_ids": [Command.set([cls.env.ref("base.group_user").id, cls.env.ref("kabay_base.group_kabay_reception").id])],
        })
        cls.maintenance = cls.env["res.users"].create({
            "name": "Mantenimiento QA avisos", "login": "kabay_notice_maintenance_test",
            "company_id": cls.company.id, "company_ids": [Command.set([cls.company.id])],
            "group_ids": [Command.set([cls.env.ref("base.group_user").id, cls.env.ref("kabay_base.group_kabay_maintenance").id])],
        })
        cls.portal_owner = cls.env["res.users"].create({
            "name": cls.owner.name, "login": "kabay_notice_portal_owner_test", "partner_id": cls.owner.id,
            "company_id": cls.company.id, "company_ids": [Command.set([cls.company.id])],
            "group_ids": [Command.set([cls.env.ref("base.group_portal").id])],
        })
        cls.portal_tenant = cls.env["res.users"].create({
            "name": cls.tenant.name, "login": "kabay_notice_portal_tenant_test", "partner_id": cls.tenant.id,
            "company_id": cls.company.id, "company_ids": [Command.set([cls.company.id])],
            "group_ids": [Command.set([cls.env.ref("base.group_portal").id])],
        })
        cls.portal_outsider = cls.env["res.users"].create({
            "name": cls.outsider.name, "login": "kabay_notice_portal_outsider_test", "partner_id": cls.outsider.id,
            "company_id": cls.company.id, "company_ids": [Command.set([cls.company.id])],
            "group_ids": [Command.set([cls.env.ref("base.group_portal").id])],
        })

    def _notice(self, scope="condominium", **kwargs):
        values = {
            "name": "Aviso QA %s" % self.env["ir.sequence"].next_by_code("kabay.notice"),
            "summary": "Resumen de prueba comunitaria",
            "content": "<p>Contenido de prueba</p>",
            "company_id": self.company.id,
            "condominium_id": self.condominium.id if scope != "company" else False,
            "scope": scope,
            "notice_type": "general",
            "priority": "normal",
            "target_role": "all",
            "publish_datetime": fields.Datetime.now(),
        }
        values.update(kwargs)
        return self.env["kabay.notice"].with_user(self.admin).create(values)

    def _publish(self, notice):
        notice.with_user(self.admin).action_publish()
        return notice

    def test_01_create_notice(self):
        notice = self._notice()
        self.assertEqual(notice.state, "draft")
        self.assertTrue(notice.reference.startswith("AV-") or notice.reference != "Nuevo")
        self.assertEqual(notice.company_id, self.company)

    def test_02_edit_draft(self):
        notice = self._notice()
        notice.with_user(self.admin).write({"name": "Título actualizado"})
        self.assertEqual(notice.name, "Título actualizado")

    def test_03_publish_immediately(self):
        notice = self._notice()
        self._publish(notice)
        self.assertEqual(notice.state, "published")
        self.assertTrue(notice.published_at)
        self.assertEqual(notice.published_by_id, self.admin)

    def test_04_schedule_future(self):
        notice = self._notice(publish_datetime=fields.Datetime.now() + timedelta(days=1))
        notice.with_user(self.admin).action_schedule()
        self.assertEqual(notice.state, "scheduled")

    def test_05_scheduled_notice_is_not_visible_before_release(self):
        notice = self._notice(publish_datetime=fields.Datetime.now() + timedelta(days=1))
        notice.with_user(self.admin).action_schedule()
        visible = self.env["kabay.notice"].with_user(self.portal_owner).search([("id", "=", notice.id)])
        self.assertFalse(visible)

    def test_06_expired_notice_is_finished_by_cron(self):
        notice = self._notice(publish_datetime=fields.Datetime.now() - timedelta(days=2), expiration_datetime=fields.Datetime.now() - timedelta(days=1))
        notice._set_state({"state": "scheduled"})
        notice._cron_update_publication_states()
        self.assertEqual(notice.state, "finished")

    def test_07_select_condominium(self):
        notice = self._notice("condominium")
        self._publish(notice)
        self.assertEqual(set(notice.recipient_ids.mapped("partner_id").ids), {self.owner.id, self.tenant.id, self.authorized.id})

    def test_08_select_valid_building(self):
        notice = self._notice("building", building_id=self.building.id)
        self._publish(notice)
        self.assertEqual(set(notice.recipient_ids.mapped("apartment_id").ids), {self.apartment.id, self.apartment2.id})

    def test_09_reject_building_from_another_condominium(self):
        with self.assertRaises(ValidationError):
            self._notice("building", building_id=self.building2.id)

    def test_10_select_apartments(self):
        notice = self._notice("apartments", apartment_ids=[Command.set([self.apartment.id])])
        self._publish(notice)
        self.assertEqual(set(notice.recipient_ids.mapped("partner_id").ids), {self.owner.id, self.tenant.id})

    def test_11_reject_apartment_from_another_company(self):
        other_company = self.env["res.company"].create({"name": "QA Empresa Avisos Externa"})
        other_condo = self.env["kabay.condominium"].create({"name": "QA Condominio Externo", "code": "NOTICE-OTHER-C", "company_id": other_company.id})
        other_building = self.env["kabay.building"].create({"name": "QA Torre Externa", "code": "NOTICE-OTHER-B", "condominium_id": other_condo.id})
        other_apartment = self.env["kabay.apartment"].create({"name": "QA Unidad Externa", "code": "NOTICE-OTHER-U", "building_id": other_building.id})
        with self.assertRaises(UserError):
            self._notice("apartments", apartment_ids=[Command.set([other_apartment.id])])

    def test_12_segment_by_resident_role(self):
        notice = self._notice(target_role="owner")
        self._publish(notice)
        self.assertEqual(set(notice.recipient_ids.mapped("partner_id").ids), {self.owner.id})

    def test_13_exclude_ended_residential_relations(self):
        today = fields.Date.context_today(self.env["kabay.notice"])
        former = self.env["res.partner"].create({"name": "Antiguo residente QA"})
        self.env["kabay.apartment.relation"].create({
            "partner_id": former.id, "apartment_id": self.apartment.id, "role": "owner",
            "date_start": today - timedelta(days=90), "date_end": today - timedelta(days=1), "state": "ended",
        })
        notice = self._notice()
        self._publish(notice)
        self.assertNotIn(former, notice.recipient_ids.mapped("partner_id"))

    def test_14_recipient_snapshot_does_not_add_later_resident(self):
        notice = self._notice()
        self._publish(notice)
        snapshot = set(notice.recipient_ids.mapped("partner_id").ids)
        new_resident = self.env["res.partner"].create({"name": "Nuevo residente QA"})
        self.env["kabay.apartment.relation"].create({
            "partner_id": new_resident.id, "apartment_id": self.apartment.id, "role": "authorized_resident",
            "date_start": fields.Date.context_today(self.env["kabay.notice"]), "state": "confirmed",
        })
        self.assertEqual(set(notice.recipient_ids.mapped("partner_id").ids), snapshot)
        self.assertNotIn(new_resident, notice.recipient_ids.mapped("partner_id"))
        self.env["kabay.apartment.relation"].search([
            ("partner_id", "=", self.owner.id), ("apartment_id", "=", self.apartment.id),
        ], limit=1).action_end()
        with self.assertRaises(AccessError):
            notice.with_user(self.portal_owner).action_mark_read()

    def test_15_opening_notice_records_individual_read(self):
        notice = self._notice()
        self._publish(notice)
        notice.with_user(self.portal_owner).action_mark_read()
        receipt = self.env["kabay.notice.read"].with_user(self.portal_owner).search([("notice_id", "=", notice.id)])
        self.assertEqual(len(receipt), 1)
        self.assertEqual(receipt.partner_id, self.owner)
        self.assertEqual(receipt.user_id, self.portal_owner)
        self.assertTrue(receipt.first_read_at)

    def test_16_repeated_read_keeps_one_first_receipt(self):
        notice = self._notice()
        self._publish(notice)
        portal_notice = notice.with_user(self.portal_owner)
        portal_notice.action_mark_read()
        first_read = self.env["kabay.notice.read"].with_user(self.portal_owner).search([("notice_id", "=", notice.id)]).first_read_at
        portal_notice.action_mark_read()
        receipts = self.env["kabay.notice.read"].with_user(self.portal_owner).search([("notice_id", "=", notice.id)])
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts.first_read_at, first_read)

    def test_17_resident_cannot_read_another_residents_receipt(self):
        notice = self._notice()
        self._publish(notice)
        notice.with_user(self.portal_owner).action_mark_read()
        receipts = self.env["kabay.notice.read"].with_user(self.portal_tenant).search([("notice_id", "=", notice.id)])
        self.assertFalse(receipts)

    def test_18_resident_cannot_access_notice_from_other_condominium(self):
        notice = self._notice("condominium", condominium_id=self.condominium2.id)
        self._publish(notice)
        hidden = self.env["kabay.notice"].with_user(self.portal_owner).search([("id", "=", notice.id)])
        self.assertFalse(hidden)
        with self.assertRaises(AccessError):
            notice.with_user(self.portal_owner).action_mark_read()

    def test_19_documents_are_private_to_recipients(self):
        notice = self._notice()
        document = self.env["kabay.notice.document"].with_user(self.admin).create({
            "notice_id": notice.id, "name": "Circular QA", "file_name": "circular.pdf", "file_data": b64encode(b"PDF QA"),
        })
        self._publish(notice)
        self.assertEqual(self.env["kabay.notice.document"].with_user(self.portal_owner).search_count([("id", "=", document.id)]), 1)
        self.assertEqual(self.env["kabay.notice.document"].with_user(self.portal_outsider).search_count([("id", "=", document.id)]), 0)

    def test_20_only_admin_can_publish_or_cancel(self):
        notice = self._notice()
        with self.assertRaises(AccessError):
            notice.with_user(self.reception).action_publish()
        self._publish(notice)
        with self.assertRaises(AccessError):
            notice.with_user(self.maintenance).action_cancel()

    def test_21_administration_can_manage_notices(self):
        notice = self._notice()
        self.assertEqual(self.env["kabay.notice"].with_user(self.admin).search_count([("id", "=", notice.id)]), 1)
        self._publish(notice)
        self.assertEqual(notice.state, "published")

    def test_22_management_can_read_but_not_modify(self):
        notice = self._notice()
        self._publish(notice)
        management_notice = self.env["kabay.notice"].with_user(self.management).browse(notice.id)
        self.assertEqual(management_notice.name, notice.name)
        self.assertEqual(management_notice.recipient_count, 3)
        with self.assertRaises(AccessError):
            management_notice.write({"name": "Alterado"})

    def test_23_finance_can_read_but_not_modify_notices(self):
        notice = self._notice()
        self._publish(notice)
        finance_notice = self.env["kabay.notice"].with_user(self.finance).browse(notice.id)
        self.assertEqual(finance_notice.state, "published")
        with self.assertRaises(AccessError):
            finance_notice.write({"name": "Alterado"})

    def test_24_reception_can_read_but_not_publish(self):
        notice = self._notice()
        self._publish(notice)
        reception_notice = self.env["kabay.notice"].with_user(self.reception).browse(notice.id)
        self.assertEqual(reception_notice.name, notice.name)
        with self.assertRaises(AccessError):
            reception_notice.action_publish()

    def test_25_maintenance_can_read_but_not_publish(self):
        notice = self._notice()
        self._publish(notice)
        maintenance_notice = self.env["kabay.notice"].with_user(self.maintenance).browse(notice.id)
        self.assertEqual(maintenance_notice.name, notice.name)
        with self.assertRaises(AccessError):
            maintenance_notice.action_publish()

    def test_26_notice_rules_isolate_companies(self):
        other_company = self.env["res.company"].create({"name": "QA Empresa Avisos Privada"})
        notice = self.env["kabay.notice"].create({
            "name": "Aviso QA otra compañía", "summary": "Solo prueba", "content": "<p>QA</p>",
            "company_id": other_company.id, "scope": "company", "notice_type": "general",
            "priority": "normal", "target_role": "all",
        })
        visible = self.env["kabay.notice"].with_user(self.finance).search([("id", "=", notice.id)])
        self.assertFalse(visible)

    def test_27_published_notice_cannot_be_edited(self):
        notice = self._notice()
        self._publish(notice)
        with self.assertRaises(UserError):
            notice.with_user(self.admin).write({"summary": "Cambio no permitido"})

    def test_28_publication_audit_is_recorded(self):
        notice = self._notice()
        self._publish(notice)
        self.assertEqual(notice.published_by_id, self.admin)
        self.assertTrue(notice.published_at)
        self.assertTrue(notice.message_ids)

    def test_29_duplicate_publication_is_rejected_without_duplicate_notice(self):
        notice = self._notice()
        self._publish(notice)
        count = self.env["kabay.notice"].search_count([("id", "=", notice.id)])
        with self.assertRaises(UserError):
            notice.with_user(self.admin).action_publish()
        self.assertEqual(self.env["kabay.notice"].search_count([("id", "=", notice.id)]), count)
        self.assertEqual(notice.state, "published")

    def test_30_notices_do_not_change_accounting_records(self):
        before_count = self.env["account.move"].search_count([])
        qa_invoice = self.env["account.move"].search([("name", "=", "INV/2026/00001")], limit=1)
        qa_before = (qa_invoice.state, qa_invoice.amount_residual, qa_invoice.payment_state) if qa_invoice else False
        self._publish(self._notice())
        self.assertEqual(self.env["account.move"].search_count([]), before_count)
        if qa_invoice:
            qa_invoice.invalidate_recordset(["state", "amount_residual", "payment_state"])
            self.assertEqual((qa_invoice.state, qa_invoice.amount_residual, qa_invoice.payment_state), qa_before)

    def test_31_scheduled_notice_is_published_by_cron_when_due(self):
        notice = self._notice(publish_datetime=fields.Datetime.now() + timedelta(days=1))
        notice.with_user(self.admin).action_schedule()
        notice._set_state({"publish_datetime": fields.Datetime.now() - timedelta(minutes=1)})
        notice._cron_update_publication_states()
        self.assertEqual(notice.state, "published")
        self.assertTrue(notice.recipient_ids)
        self.assertTrue(notice.published_at)

    def test_32_people_scope_only_snapshots_selected_current_resident(self):
        notice = self._notice("contacts", target_partner_ids=[Command.set([self.owner.id])])
        self._publish(notice)
        self.assertEqual(set(notice.recipient_ids.mapped("partner_id").ids), {self.owner.id})

    def test_33_cancelled_notice_disappears_from_portal(self):
        notice = self._notice()
        self._publish(notice)
        notice.with_user(self.admin).action_cancel()
        self.assertEqual(notice.state, "cancelled")
        self.assertFalse(self.env["kabay.notice"].with_user(self.portal_owner).search([("id", "=", notice.id)]))

    def test_34_only_allowed_document_types_are_accepted(self):
        notice = self._notice()
        with self.assertRaises(ValidationError):
            self.env["kabay.notice.document"].with_user(self.admin).create({
                "notice_id": notice.id, "name": "Ejecutable QA", "file_name": "malware.exe", "file_data": b64encode(b"test"),
            })

    def test_35_company_schedule_freezes_admins_authorized_condominiums(self):
        self.condominium2.write({"manager_id": self.management.id})
        notice = self._notice("company", publish_datetime=fields.Datetime.now() + timedelta(days=1))
        notice.with_user(self.admin).action_schedule()
        self.assertIn(self.condominium, notice.publication_condominium_ids)
        self.assertNotIn(self.condominium2, notice.publication_condominium_ids)
        notice._set_state({"publish_datetime": fields.Datetime.now() - timedelta(minutes=1)})
        notice._cron_update_publication_states()
        self.assertNotIn(self.outsider, notice.recipient_ids.mapped("partner_id"))
