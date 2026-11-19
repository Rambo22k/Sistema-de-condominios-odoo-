from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.addons.kabay_base.tests.common import create_kabay_test_company, set_test_partner_accounts


@tagged("post_install", "-at_install")
class TestKabayNotifications(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company, cls.accounts, cls.sales_journal, cls.bank_journal = create_kabay_test_company(
            cls.env, "Kabay Notifications Test Company",
        )
        cls.condo = cls.env["kabay.condominium"].create({
            "name": "QA Notifications Condo", "code": "NOTIF-QA", "company_id": cls.company.id,
        })
        cls.building = cls.env["kabay.building"].create({
            "name": "QA Notifications Tower", "code": "NOTIF-T1", "condominium_id": cls.condo.id,
        })
        cls.apartment = cls.env["kabay.apartment"].create({
            "name": "N-101", "code": "NOTIF-N101", "building_id": cls.building.id,
        })
        cls.partner = cls.env["res.partner"].create({
            "name": "Resident Notification QA", "email": "notification-qa@example.invalid",
        })
        cls.no_email_partner = cls.env["res.partner"].create({"name": "Resident Without Email QA"})
        set_test_partner_accounts(cls.partner, cls.company, cls.accounts)
        set_test_partner_accounts(cls.no_email_partner, cls.company, cls.accounts)
        cls.relation = cls.env["kabay.apartment.relation"].create({
            "partner_id": cls.partner.id, "apartment_id": cls.apartment.id,
            "role": "owner", "date_start": fields.Date.today(),
        })
        cls.relation.action_confirm()
        cls.settings = cls.env["kabay.notification.settings"].sudo()._for_company(cls.company)
        cls.settings.write({"delivery_enabled": False, "active": True})
        cls.portal_user = cls.env["res.users"].create({
            "name": cls.partner.name, "login": "kabay_notifications_portal_qa",
            "partner_id": cls.partner.id, "company_id": cls.company.id,
            "company_ids": [Command.set([cls.company.id])],
            "group_ids": [Command.set([cls.env.ref("base.group_portal").id])],
        })
        cls.manager_user = cls.env["res.users"].create({
            "name": "Notifications QA Manager", "login": "kabay_notifications_manager_qa",
            "company_id": cls.company.id, "company_ids": [Command.set([cls.company.id])],
            "group_ids": [Command.set([cls.env.ref("base.group_user").id, cls.env.ref("kabay_base.group_kabay_manager").id])],
        })
        cls.finance_user = cls.env["res.users"].create({
            "name": "Notifications QA Finance", "login": "kabay_notifications_finance_qa",
            "company_id": cls.company.id, "company_ids": [Command.set([cls.company.id])],
            "group_ids": [Command.set([cls.env.ref("base.group_user").id, cls.env.ref("kabay_base.group_kabay_finance").id])],
        })
        cls.team = cls.env["helpdesk.team"].search([
            ("company_id", "=", cls.company.id), ("kabay_resident_team", "=", True),
        ], limit=1)
        cls.category = cls.env.ref("kabay_helpdesk.category_maintenance")
        cls.income_account = cls.accounts["41020100"]
        cls.product = cls.env["product.product"].with_company(cls.company).create({
            "name": "Notification QA Product", "type": "service",
            "property_account_income_id": cls.income_account.id,
            "taxes_id": [Command.clear()],
        })

    def _event(self, event_type="notice_published", *, source=None, recipient=None, identifier="e1", category="notices", data=None):
        return self.env["kabay.notification"]._capture(
            source=source or self.partner, event_type=event_type, category=category,
            recipient=recipient or self.partner, company=self.company,
            event_identifier=identifier, data=data or {"title": "QA event"},
        )

    def _invoice(self, *, due_date=None, posted=True, move_type="out_invoice"):
        journal = self.sales_journal
        move = self.env["account.move"].with_company(self.company).create({
            "move_type": move_type, "company_id": self.company.id,
            "journal_id": journal.id, "partner_id": self.partner.id,
            "invoice_date": fields.Date.today(),
            "invoice_date_due": due_date or fields.Date.today() + timedelta(days=30),
            "kabay_condominium_id": self.condo.id, "kabay_apartment_id": self.apartment.id,
            "kabay_responsible_id": self.partner.id,
            "invoice_line_ids": [Command.create({
                "name": "Cuota QA notifications", "product_id": self.product.id,
                "quantity": 1, "price_unit": 100, "account_id": self.income_account.id,
            })],
        })
        if posted:
            move.action_post()
        return move

    def _ticket(self):
        stage = self.team.stage_ids.filtered(lambda row: row.kabay_state == "new")[:1]
        return self.env["helpdesk.ticket"].create({
            "name": "Solicitud QA notifications", "description": "Solo descripción pública del residente.",
            "partner_id": self.partner.id, "team_id": self.team.id, "stage_id": stage.id,
            "kabay_apartment_id": self.apartment.id, "kabay_relation_id": self.relation.id,
            "kabay_category_id": self.category.id,
        })

    def test_01_posted_kabay_invoice_creates_event_for_stored_responsible(self):
        invoice = self._invoice()
        event = self.env["kabay.notification"].search([
            ("source_model", "=", "account.move"), ("source_res_id", "=", invoice.id),
            ("event_type", "=", "invoice_posted"),
        ])
        self.assertEqual(len(event), 1)
        self.assertEqual(event.recipient_id, self.partner)
        self.assertEqual(event.state, "pending")

    def test_02_draft_invoice_does_not_create_publication_event(self):
        invoice = self._invoice(posted=False)
        self.assertFalse(self.env["kabay.notification"].search_count([
            ("source_model", "=", "account.move"), ("source_res_id", "=", invoice.id),
            ("event_type", "in", ["invoice_posted", "installment_invoice_posted"]),
        ]))

    def test_03_cancelled_invoice_does_not_create_publication_event(self):
        invoice = self._invoice(posted=False)
        invoice.button_cancel()
        self.assertFalse(self.env["kabay.notification"].search_count([
            ("source_model", "=", "account.move"), ("source_res_id", "=", invoice.id),
        ]))

    def test_04_reminder_is_created_before_due_date(self):
        due = fields.Date.today() + timedelta(days=self.settings.reminder_days_before_first)
        invoice = self._invoice(due_date=due)
        self.env["kabay.notification"]._cron_generate_invoice_reminders(self.settings)
        event = self.env["kabay.notification"].search([
            ("source_res_id", "=", invoice.id), ("event_type", "=", "invoice_reminder"),
        ])
        self.assertTrue(event)
        self.assertIn("vence en", event.event_data["intro"])

    def test_05_reminder_is_created_after_due_date(self):
        due = fields.Date.today() - timedelta(days=self.settings.reminder_days_after)
        invoice = self._invoice(due_date=due)
        self.env["kabay.notification"]._cron_generate_invoice_reminders(self.settings)
        event = self.env["kabay.notification"].search([
            ("source_res_id", "=", invoice.id), ("event_type", "=", "invoice_reminder"),
        ])
        self.assertTrue(event)
        self.assertIn("vencida", event.event_data["intro"])

    def test_06_paid_invoice_is_not_eligible_for_reminder(self):
        invoice = SimpleNamespace(
            state="posted", move_type="out_invoice", amount_residual=0,
            invoice_date_due=fields.Date.today(), kabay_responsible_id=self.partner,
            kabay_financing_installment_id=False,
        )
        self.assertFalse(self.env["kabay.notification"]._kabay_is_invoice_reminder_eligible(invoice))

    def test_07_repeated_reminder_event_is_deduplicated(self):
        first = self._event("invoice_reminder", identifier="due:2026-11-22:offset:-7", category="billing")
        second = self._event("invoice_reminder", identifier="due:2026-11-22:offset:-7", category="billing")
        self.assertEqual(first.id, second.id)
        self.assertEqual(self.env["kabay.notification"].search_count([
            ("source_res_id", "=", self.partner.id), ("event_type", "=", "invoice_reminder"),
        ]), 1)

    def test_08_submitted_deposit_event_is_distinct(self):
        event = self._event("deposit_submitted", identifier="deposit:submitted", category="deposits",
                            data={"title": "DP-QA-1", "intro": "Declarado para revisión."})
        self.assertEqual(event.event_type, "deposit_submitted")
        self.assertNotIn("pagado", event.event_data["intro"].lower())

    def test_09_declaration_and_reconciled_payment_are_separate_events(self):
        declared = self._event("deposit_submitted", identifier="deposit:submit", category="deposits")
        applied = self._event("deposit_applied", identifier="deposit:applied", category="deposits")
        self.assertNotEqual(declared.event_type, applied.event_type)
        self.assertEqual(applied.event_type, "deposit_applied")

    def test_10_rejected_deposit_has_its_own_event(self):
        event = self._event("deposit_rejected", identifier="deposit:rejected", category="deposits",
                            data={"title": "DP-QA-2", "message": "Referencia no localizada."})
        self.assertEqual(event.event_type, "deposit_rejected")
        self.assertIn("Referencia no localizada", str(event.email_body_html))

    def test_11_successful_ticket_creation_notifies_its_requester(self):
        ticket = self._ticket()
        event = self.env["kabay.notification"].search([
            ("source_model", "=", "helpdesk.ticket"), ("source_res_id", "=", ticket.id),
            ("event_type", "=", "ticket_created"),
        ])
        self.assertEqual(event.recipient_id, self.partner)

    def test_12_internal_helpdesk_note_is_never_sent(self):
        ticket = self._ticket()
        ticket.message_post(body="Contenido interno CONFIDENCIAL", subtype_xmlid="mail.mt_note", message_type="comment")
        self.assertFalse(self.env["kabay.notification"].search_count([
            ("source_model", "=", "helpdesk.ticket"), ("source_res_id", "=", ticket.id),
            ("event_type", "=", "ticket_public_reply"),
        ]))

    def test_13_public_helpdesk_reply_creates_resident_event(self):
        ticket = self._ticket()
        ticket.message_post(body="Respuesta visible para el residente", subtype_xmlid="mail.mt_comment", message_type="comment")
        event = self.env["kabay.notification"].search([
            ("source_model", "=", "helpdesk.ticket"), ("source_res_id", "=", ticket.id),
            ("event_type", "=", "ticket_public_reply"),
        ])
        self.assertTrue(event)
        self.assertIn("Respuesta visible", str(event.email_body_html))

    def test_14_published_notice_uses_its_recipient_snapshot(self):
        notice = self.env["kabay.notice"].create({
            "name": "Aviso QA notification", "summary": "Resumen", "content": "<p>Comunicado público</p>",
            "company_id": self.company.id, "condominium_id": self.condo.id,
            "scope": "condominium", "notice_type": "general", "priority": "normal",
            "publish_datetime": fields.Datetime.now(),
        })
        notice.action_publish()
        event = self.env["kabay.notification"].search([
            ("source_model", "=", "kabay.notice"), ("source_res_id", "=", notice.id),
            ("event_type", "=", "notice_published"), ("recipient_id", "=", self.partner.id),
        ])
        self.assertTrue(event)
        self.assertIn("Comunicado público", str(event.email_body_html))

    def test_15_notice_events_do_not_recalculate_recipients_from_new_relations(self):
        notice = self.env["kabay.notice"].create({
            "name": "Aviso snapshot QA", "summary": "Resumen", "content": "<p>Aviso</p>",
            "company_id": self.company.id, "condominium_id": self.condo.id,
            "scope": "condominium", "notice_type": "general", "priority": "normal",
            "publish_datetime": fields.Datetime.now(),
        })
        notice.action_publish()
        before = self.env["kabay.notification"].search_count([
            ("source_model", "=", "kabay.notice"), ("source_res_id", "=", notice.id),
        ])
        new_partner = self.env["res.partner"].create({"name": "Later resident QA", "email": "later@example.invalid"})
        self.env["kabay.apartment.relation"].create({
            "partner_id": new_partner.id, "apartment_id": self.apartment.id,
            "role": "tenant", "date_start": fields.Date.today(), "state": "confirmed",
        })
        notice._kabay_notify_published()
        after = self.env["kabay.notification"].search_count([
            ("source_model", "=", "kabay.notice"), ("source_res_id", "=", notice.id),
        ])
        self.assertEqual(after, before)
        self.assertFalse(self.env["kabay.notification"].search([
            ("source_model", "=", "kabay.notice"), ("source_res_id", "=", notice.id),
            ("recipient_id", "=", new_partner.id),
        ]))

    def test_16_financing_schedule_creates_installment_notifications(self):
        contract = self.env["kabay.financing.contract"].create({
            "condominium_id": self.condo.id, "apartment_id": self.apartment.id,
            "buyer_id": self.partner.id, "creditor_id": self.company.partner_id.id,
            "company_id": self.company.id, "currency_id": self.company.currency_id.id,
            "product_id": self.product.id, "purchase_price": 200,
            "down_payment": 0, "installment_count": 2, "frequency": "monthly",
            "start_date": fields.Date.today() + timedelta(days=45), "invoice_lead_days": 0,
        })
        contract.action_confirm()
        events = self.env["kabay.notification"].search([
            ("source_model", "=", "kabay.financing.installment"),
            ("event_type", "=", "installment_schedule"),
            ("recipient_id", "=", self.partner.id),
        ])
        self.assertEqual(len(events), 2)

    def test_17_unique_key_protects_duplicate_concurrent_capture(self):
        first = self._event("notice_published", identifier="notice:unique-lock")
        duplicate = self._event("notice_published", identifier="notice:unique-lock")
        self.assertEqual(first.id, duplicate.id)

    def test_18_mail_queue_error_is_logged_without_sending(self):
        event = self._event("invoice_posted", identifier="mail:error", category="billing")
        self.settings.write({"delivery_enabled": True})
        template = self.env.ref("kabay_notifications.mail_template_kabay_billing")
        server_model = self.env["ir.mail_server"].sudo()
        private_error = "simulated failure for private@example.invalid"
        with patch.object(type(server_model), "search_count", return_value=1), \
                patch.object(type(template), "send_mail", side_effect=RuntimeError(private_error)):
            event._process_one()
        self.assertEqual(event.state, "failed")
        self.assertEqual(event.attempt_count, 1)
        self.assertNotIn("private@example.invalid", event.last_error)
        self.assertIn("registro técnico protegido", event.last_error)

    def test_19_manual_retry_is_bounded_by_configuration(self):
        event = self._event("invoice_posted", identifier="mail:retry", category="billing")
        event.sudo().write({"state": "failed", "attempt_count": 1})
        event.with_user(self.manager_user).action_retry()
        self.assertEqual(event.state, "pending")
        event.sudo().write({"state": "failed", "attempt_count": self.settings.max_attempts})
        with self.assertRaises(UserError):
            event.with_user(self.manager_user).action_retry()

    def test_20_events_keep_their_source_company(self):
        other_company = self.env["res.company"].create({"name": "Notification QA Other Company"})
        event = self.env["kabay.notification"]._capture(
            source=self.partner, event_type="notice_published", category="notices",
            recipient=self.partner, company=other_company, event_identifier="multi-company:1",
        )
        self.assertEqual(event.company_id, other_company)

    def test_21_portal_user_cannot_read_global_notification_history(self):
        with self.assertRaises(AccessError):
            self.env["kabay.notification"].with_user(self.portal_user).search([])

    def test_22_resident_preferences_suppress_only_optional_categories(self):
        self.partner.write({"kabay_notify_notices": False})
        optional = self._event("notice_published", identifier="prefs:notice")
        essential = self._event("invoice_posted", identifier="prefs:invoice", category="billing")
        self.assertEqual(optional.state, "skipped")
        self.assertEqual(essential.state, "pending")

    def test_23_notification_capture_does_not_change_invoice_or_payment_data(self):
        invoice = self._invoice()
        before = (invoice.state, invoice.payment_state, invoice.amount_total, invoice.amount_residual)
        self._event("invoice_posted", source=invoice, identifier="accounting:immutable", category="billing")
        invoice.invalidate_recordset(["state", "payment_state", "amount_total", "amount_residual"])
        self.assertEqual((invoice.state, invoice.payment_state, invoice.amount_total, invoice.amount_residual), before)

    def test_24_credit_note_has_a_distinct_notification_type(self):
        credit = self._invoice(move_type="out_refund")
        event = self.env["kabay.notification"].search([
            ("source_model", "=", "account.move"), ("source_res_id", "=", credit.id),
        ])
        self.assertEqual(event.event_type, "credit_note_posted")
        self.assertIn("nota de crédito", event.event_data["intro"].lower())

    def test_25_ticket_assignment_and_state_change_create_audit_events(self):
        ticket = self._ticket()
        assigned_stage = self.team.stage_ids.filtered(lambda row: row.kabay_state == "assigned")[:1]
        ticket.write({"stage_id": assigned_stage.id, "user_id": self.manager_user.id})
        events = self.env["kabay.notification"].search([
            ("source_model", "=", "helpdesk.ticket"), ("source_res_id", "=", ticket.id),
            ("event_type", "in", ["ticket_assigned", "ticket_state"]),
        ])
        self.assertEqual(set(events.mapped("event_type")), {"ticket_assigned", "ticket_state"})

    def test_26_finance_history_is_limited_to_accounting_categories(self):
        billing = self._event("invoice_posted", identifier="finance:billing", category="billing")
        ticket = self._event("ticket_created", identifier="finance:ticket", category="helpdesk")
        visible = self.env["kabay.notification"].with_user(self.finance_user).search([
            ("id", "in", [billing.id, ticket.id]),
        ])
        self.assertEqual(visible.ids, billing.ids)

    def test_27_system_admin_can_read_standard_portal_invite_templates(self):
        template = self.env["mail.template"].sudo().create({
            "name": "Portal invite access QA",
            "model_id": self.env["ir.model"]._get_id("res.partner"),
            "subject": "Portal invite QA",
            "body_html": "<p>QA only</p>",
        })
        system_admin = self.env.ref("base.user_admin")
        self.assertEqual(template.with_user(system_admin).read(["name"])[0]["name"], template.name)
        with self.assertRaises(AccessError):
            template.with_user(self.manager_user).read(["name"])
