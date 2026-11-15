from odoo import fields
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError
from types import SimpleNamespace


@tagged("post_install", "-at_install")
class TestKabayReports(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env["res.company"].create({
            "name": "Reports QA Other Company", "currency_id": cls.company.currency_id.id,
        })
        cls.other_condo = cls.env["kabay.condominium"].create({
            "name": "Reports QA Other Condo", "code": "RPT-QA-OTHER", "company_id": cls.other_company.id,
        })
        cls.condo = cls.env["kabay.condominium"].create({
            "name": "Reports QA Condo", "code": "RPT-QA", "company_id": cls.company.id,
        })
        cls.building = cls.env["kabay.building"].create({
            "name": "Reports QA Tower", "code": "RPT-T1", "condominium_id": cls.condo.id,
        })
        cls.apartment = cls.env["kabay.apartment"].create({
            "name": "Reports QA Unit", "code": "RPT-101", "building_id": cls.building.id,
        })

    def _dashboard(self, **values):
        return self.env["kabay.report.dashboard"].create({"company_id": self.company.id, **values})

    def test_general_counts_and_filter_by_condominium(self):
        panel = self._dashboard(condominium_id=self.condo.id)
        self.assertEqual(panel.condominium_count, 1)
        self.assertEqual(panel.building_count, 1)
        self.assertEqual(panel.apartment_count, 1)
        self.assertEqual(panel.occupied_count, 0)
        self.assertEqual(panel.without_current_relation_count, 1)

    def test_current_residential_relation_marks_occupied(self):
        partner = self.env["res.partner"].create({"name": "Reports QA Resident"})
        self.env["kabay.apartment.relation"].create({
            "partner_id": partner.id, "apartment_id": self.apartment.id, "role": "tenant",
            "date_start": fields.Date.today(), "state": "confirmed", "active": True,
        })
        panel = self._dashboard(condominium_id=self.condo.id)
        self.assertEqual(panel.occupied_count, 1)
        self.assertEqual(panel.tenant_count, 1)

    def test_company_filter_does_not_include_other_company_records(self):
        panel = self._dashboard(company_id=self.company.id)
        expected_condos = self.env["kabay.condominium"].search_count([("company_id", "=", self.company.id)])
        self.assertEqual(panel.condominium_count, expected_condos)
        self.assertNotEqual(panel.company_id, self.other_company)

    def test_dashboard_date_range_validation(self):
        with self.assertRaises(ValidationError):
            self._dashboard(date_from="2026-12-31", date_to="2026-01-01")

    def test_receivable_ageing_bucket_boundaries(self):
        panel = self._dashboard(condominium_id=self.condo.id)
        as_of = fields.Date.to_date("2026-11-14")
        self.assertEqual(panel._receivable_age_bucket(fields.Date.to_date("2026-10-15"), as_of), "receivable_1_30")
        self.assertEqual(panel._receivable_age_bucket(fields.Date.to_date("2026-09-15"), as_of), "receivable_31_60")
        self.assertEqual(panel._receivable_age_bucket(fields.Date.to_date("2026-08-16"), as_of), "receivable_61_90")
        self.assertEqual(panel._receivable_age_bucket(fields.Date.to_date("2026-08-15"), as_of), "receivable_over_90")

    def test_accounting_fixture_is_never_used_or_modified(self):
        invoice = SimpleNamespace(
            state="posted", move_type="out_invoice", amount_total_signed=1180,
            amount_residual_signed=1180, invoice_date_due=fields.Date.to_date("2026-11-14"),
            payment_state="not_paid",
        )
        before = invoice.__dict__.copy()
        self._dashboard(condominium_id=self.condo.id)._summarize_invoices(
            [invoice], [], fields.Date.to_date("2026-11-14"),
        )
        self.assertEqual(invoice.__dict__, before)

    @staticmethod
    def _invoice_stub(**overrides):
        values = {
            "state": "posted", "move_type": "out_invoice", "amount_total_signed": 100.0,
            "amount_residual_signed": 100.0, "invoice_date_due": fields.Date.to_date("2026-11-14"),
            "payment_state": "not_paid",
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_invoice_total_uses_posted_customer_invoices(self):
        panel = self._dashboard(condominium_id=self.condo.id)
        result = panel._summarize_invoices(
            [self._invoice_stub(amount_total_signed=350), self._invoice_stub(amount_total_signed=650)],
            [], fields.Date.to_date("2026-11-14"),
        )
        self.assertEqual(result["invoiced_total"], 1000)

    def test_receivable_total_uses_residual_not_invoice_total(self):
        panel = self._dashboard(condominium_id=self.condo.id)
        invoice = self._invoice_stub(amount_total_signed=1000, amount_residual_signed=275)
        result = panel._summarize_invoices([invoice], [], fields.Date.to_date("2026-11-14"))
        self.assertEqual(result["receivable_total"], 275)
        self.assertEqual(result["open_invoice_count"], 1)

    def test_overdue_requires_past_due_date_and_positive_residual(self):
        panel = self._dashboard(condominium_id=self.condo.id)
        result = panel._summarize_invoices([
            self._invoice_stub(invoice_date_due=fields.Date.to_date("2026-11-13")),
            self._invoice_stub(invoice_date_due=fields.Date.to_date("2026-11-15"), amount_residual_signed=25),
            self._invoice_stub(invoice_date_due=fields.Date.to_date("2026-11-10"), amount_residual_signed=0, payment_state="paid"),
        ], [], fields.Date.to_date("2026-11-14"))
        self.assertEqual(result["overdue_total"], 100)
        self.assertEqual(result["overdue_invoice_count"], 1)

    def test_cancelled_invoice_is_excluded(self):
        panel = self._dashboard(condominium_id=self.condo.id)
        result = panel._summarize_invoices([
            self._invoice_stub(state="cancel", amount_total_signed=9999),
        ], [], fields.Date.to_date("2026-11-14"))
        self.assertEqual(result["invoiced_total"], 0)
        self.assertEqual(result["receivable_total"], 0)

    def test_credit_notes_are_reported_separately_as_positive_value(self):
        panel = self._dashboard(condominium_id=self.condo.id)
        credit = self._invoice_stub(move_type="out_refund", amount_total_signed=-75, amount_residual_signed=-75)
        result = panel._summarize_invoices([], [credit], fields.Date.to_date("2026-11-14"))
        self.assertEqual(result["credit_note_total"], 75)
        self.assertEqual(result["invoiced_total"], 0)

    def test_only_fully_attributable_reconciled_payments_count(self):
        panel = self._dashboard(condominium_id=self.condo.id)
        self.assertTrue(panel._payment_is_fully_attributable([1, 2], {1, 2, 3}))
        self.assertFalse(panel._payment_is_fully_attributable([1, 9], {1, 2, 3}))
        self.assertFalse(panel._payment_is_fully_attributable([], {1, 2, 3}))

    def test_installment_summary_distinguishes_paid_from_generated(self):
        panel = self._dashboard(condominium_id=self.condo.id)
        lines = [SimpleNamespace(state=s) for s in ("scheduled", "draft", "pending", "paid", "overdue")]
        result = panel._summarize_installments(lines)
        self.assertEqual(result, {"total": 5, "paid": 1, "overdue": 1})

    def test_operational_ticket_states_are_counted_by_real_kabay_codes(self):
        panel = self._dashboard(condominium_id=self.condo.id)
        tickets = [SimpleNamespace(kabay_state=s) for s in ("new", "waiting_resident", "in_progress", "resolved", "closed", "cancelled")]
        self.assertEqual(panel._summarize_tickets(tickets), {
            "open": 2, "in_progress": 1, "resolved": 2, "cancelled": 1,
        })

    def test_declared_deposit_alone_is_not_a_collection(self):
        panel = self._dashboard(condominium_id=self.condo.id)
        declared = SimpleNamespace(state="applied", amount=500.0, payment_ids=[])
        invoice = self._invoice_stub()
        result = panel._summarize_invoices([invoice], [], fields.Date.to_date("2026-11-14"))
        self.assertEqual(declared.amount, 500)
        self.assertFalse(declared.payment_ids)
        self.assertEqual(result["collected_total"], 0)

    def test_portal_user_has_no_dashboard_model_access(self):
        portal_group = self.env.ref("base.group_portal")
        user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Reports QA Portal User", "login": "reports-qa-portal-user",
            "company_id": self.company.id, "company_ids": [(6, 0, [self.company.id])],
            "group_ids": [(6, 0, [portal_group.id])],
        })
        dashboard_model = self.env["kabay.report.dashboard"].with_user(user)
        self.assertFalse(dashboard_model.check_access_rights("read", raise_exception=False))
