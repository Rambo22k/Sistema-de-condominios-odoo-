from datetime import date

from odoo.tests import TransactionCase, tagged
from odoo.exceptions import AccessError, UserError, ValidationError


@tagged("post_install", "-at_install")
class TestKabayBilling(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.old_country = cls.company.country_id
        cls.old_currency = cls.company.currency_id
        cls.dop = cls.env.ref("base.DOP")
        cls.dop.active = True
        cls.company.write({"country_id": cls.env.ref("base.do").id, "currency_id": cls.dop.id})
        cls.condo = cls.env["kabay.condominium"].create({"name": "Test Condo", "code": "T-BILL", "company_id": cls.company.id})
        cls.building = cls.env["kabay.building"].create({"name": "Torre A", "code": "T-A", "condominium_id": cls.condo.id})
        cls.apartment = cls.env["kabay.apartment"].create({"name": "A-101", "code": "A-101", "building_id": cls.building.id})
        cls.account = cls.env["account.account"].search([("company_ids", "in", cls.company.id), ("account_type", "=", "income")], limit=1)
        if not cls.account:
            cls.account = cls.env["account.account"].create({"name": "Test Income", "code": "T9000", "account_type": "income", "company_ids": [(6, 0, [cls.company.id])]})
        cls.journal = cls.env["account.journal"].search([("company_id", "=", cls.company.id), ("type", "=", "sale")], limit=1)
        cls.product = cls.env["product.product"].create({"name": "Cuota de prueba", "type": "service", "property_account_income_id": cls.account.id, "taxes_id": [(5, 0, 0)]})
        cls.partner = cls.env["res.partner"].create({"name": "Responsable prueba"})
        cls.rule = cls.env["kabay.fee.rule"].create({"name": "Mantenimiento", "condominium_id": cls.condo.id,
            "product_id": cls.product.id, "concept": "maintenance", "amount": 100, "currency_id": cls.dop.id,
            "periodicity": "monthly", "date_start": date(2026, 1, 1), "due_day": 15})
        cls.responsibility = cls.env["kabay.payment.responsibility"].create({"apartment_id": cls.apartment.id,
            "fee_rule_id": cls.rule.id, "partner_id": cls.partner.id, "date_start": date(2026, 1, 1), "state": "confirmed"})
        cls.finance = cls.env["res.users"].create({"name": "Finanzas prueba", "login": "kabay_finance_test",
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id, cls.env.ref("kabay_base.group_kabay_finance").id])]})

    def _batch(self, rules=None):
        return self.env["kabay.billing.batch"].create({"condominium_id": self.condo.id,
            "period_start": date(2026, 11, 1), "period_end": date(2026, 11, 30),
            "invoice_date": date(2026, 11, 1), "due_date": date(2026, 11, 15),
            "fee_rule_ids": [(6, 0, (rules or self.rule).ids)]})

    def test_periodicities_and_future_rate(self):
        for periodicity in ("monthly", "quarterly", "yearly", "single"):
            rule = self.rule.copy({"name": periodicity, "periodicity": periodicity})
            self.assertEqual(rule.periodicity, periodicity)
        before = self.rule.amount
        self.rule.copy({"name": "Future", "amount": 125, "date_start": date(2027, 1, 1)})
        self.assertEqual(self.rule.amount, before)

    def test_prepare_and_generate_draft_invoice_idempotently(self):
        batch = self._batch()
        batch.action_prepare()
        self.assertEqual(batch.state, "prepared")
        self.assertEqual(batch.ready_count, 1)
        self.assertFalse(batch.line_ids.mapped("move_id"))
        batch.with_user(self.finance).action_confirm()
        invoice = batch.line_ids.move_id
        self.assertEqual(len(invoice), 1)
        self.assertEqual(invoice.state, "draft")
        self.assertEqual(invoice.amount_total, 100)
        self.assertEqual(invoice.kabay_apartment_id, self.apartment)
        self.assertEqual(invoice.invoice_line_ids.kabay_fee_rule_id, self.rule)
        self.assertEqual(invoice.invoice_date_due, date(2026, 11, 15))
        self.assertEqual(invoice.amount_residual, 100)
        invoice.with_user(self.finance).action_post()
        self.assertEqual(invoice.state, "posted")
        with self.assertRaises(UserError):
            invoice.with_user(self.finance).write({"kabay_billing_key": "forged-after-post"})
        repeat = self._batch()
        repeat.action_prepare()
        self.assertIn("duplicate", repeat.line_ids.mapped("status"))

    def test_finance_cannot_forge_preview_lines_or_skip_batch_transitions(self):
        batch = self._batch()
        batch.with_user(self.finance).action_prepare()
        line = batch.line_ids[:1]
        with self.assertRaises(AccessError):
            line.with_user(self.finance).write({"amount": 1, "partner_id": self.partner.id})
        with self.assertRaises(AccessError):
            self.env["kabay.billing.batch.line"].with_user(self.finance).create({
                "batch_id": batch.id, "apartment_id": self.apartment.id,
                "amount": 1, "status": "ready",
            })
        with self.assertRaises(UserError):
            batch.with_user(self.finance).write({"state": "confirmed"})
        with self.assertRaises(UserError):
            batch.with_user(self.finance).write({"period_start": date(2026, 12, 1)})
        batch.with_user(self.finance).action_prepare()
        self.assertEqual(batch.state, "prepared")

    def test_missing_tariff_and_responsible_are_reported(self):
        self.rule.write({"apartment_ids": [(6, 0, [self.apartment.id])]})
        other_building = self.env["kabay.building"].create({"name": "B", "code": "T-B", "condominium_id": self.condo.id})
        self.env["kabay.apartment"].create({"name": "B-1", "code": "B-1", "building_id": other_building.id})
        batch = self._batch()
        batch.action_prepare()
        self.assertIn("no_fee", batch.line_ids.mapped("status"))
        self.responsibility.with_user(self.finance).write({"state": "ended"})
        other = self._batch()
        other.action_prepare()
        self.assertIn("no_responsible", other.line_ids.mapped("status"))

    def test_responsibility_history_and_reception_cannot_confirm(self):
        self.responsibility.with_user(self.finance).write({"date_end": date(2026, 10, 31), "state": "ended"})
        newer = self.env["kabay.payment.responsibility"].with_user(self.finance).create({"apartment_id": self.apartment.id,
            "fee_rule_id": self.rule.id, "partner_id": self.env["res.partner"].create({"name": "Nuevo"}).id,
            "date_start": date(2026, 11, 1), "state": "confirmed"})
        self.assertNotEqual(newer.partner_id, self.responsibility.partner_id)
        batch = self._batch()
        batch.action_prepare()
        reception = self.env["res.users"].create({"name": "Recepción prueba", "login": "kabay_reception_test", "group_ids": [(6, 0, [self.env.ref("base.group_user").id, self.env.ref("kabay_base.group_kabay_reception").id])]})
        with self.assertRaises(UserError):
            batch.with_user(reception).action_confirm()

    def test_quarter_year_single_rule_values(self):
        for period in ("quarterly", "yearly", "single"):
            record = self.rule.copy({"periodicity": period, "name": period})
            self.assertEqual(record.periodicity, period)

    def test_bimonthly_and_period_boundaries(self):
        rule = self.rule.copy({"periodicity": "bimonthly", "date_start": date(2026, 11, 1)})
        self.assertTrue(rule.is_due_in_period(date(2026, 11, 1), date(2026, 11, 30)))
        self.assertFalse(rule.is_due_in_period(date(2026, 12, 1), date(2026, 12, 31)))
        self.assertTrue(rule.is_due_in_period(date(2027, 1, 1), date(2027, 1, 31)))
        single = self.rule.copy({"periodicity": "single", "date_start": date(2026, 12, 3)})
        self.assertTrue(single.is_due_in_period(date(2026, 12, 1), date(2026, 12, 31)))
        self.assertFalse(single.is_due_in_period(date(2027, 1, 1), date(2027, 1, 31)))

    def test_due_day_clamps_month_end_and_leap_years(self):
        cases = [
            (5, date(2027, 2, 1), date(2027, 2, 5)),
            (30, date(2027, 2, 1), date(2027, 2, 28)),
            (31, date(2027, 2, 1), date(2027, 2, 28)),
            (31, date(2028, 2, 1), date(2028, 2, 29)),
            (30, date(2028, 2, 1), date(2028, 2, 29)),
        ]
        for day, period, expected in cases:
            rule = self.rule.copy({"name": "Vence %s" % day, "due_day": day})
            self.assertEqual(rule.get_due_date(period, date(2028, 3, 15)), expected)
        quarterly = self.rule.copy({"name": "Trimestral QA", "periodicity": "quarterly", "date_start": date(2027, 1, 1), "due_day": 30})
        self.assertTrue(quarterly.is_due_in_period(date(2027, 4, 1), date(2027, 4, 30)))
        self.assertFalse(quarterly.is_due_in_period(date(2027, 5, 1), date(2027, 5, 31)))
        self.assertEqual(quarterly.get_due_date(date(2027, 4, 1), date(2027, 4, 1)), date(2027, 4, 30))

    def test_due_day_override_fallback_and_distinct_invoice_due_dates(self):
        self.rule.write({"due_day": 5})
        second_rule = self.rule.copy({"name": "Cuota con día 30", "amount": 50, "due_day": 30})
        self.env["kabay.payment.responsibility"].create({"apartment_id": self.apartment.id, "fee_rule_id": second_rule.id,
            "partner_id": self.partner.id, "date_start": date(2026, 1, 1), "state": "confirmed"})
        batch = self._batch(rules=self.rule | second_rule)
        batch.action_prepare()
        self.assertEqual(set(batch.line_ids.mapped("due_date")), {date(2026, 11, 5), date(2026, 11, 30)})
        batch.with_user(self.finance).action_confirm()
        self.assertEqual(set(batch.line_ids.mapped("move_id.invoice_date_due")), {date(2026, 11, 5), date(2026, 11, 30)})
        self.assertEqual(len(batch.line_ids.mapped("move_id")), 2)

        self.rule.write({"due_day": False})
        fallback = self._batch()
        fallback.write({"due_date": date(2026, 11, 20)})
        fallback.action_prepare()
        self.assertEqual(fallback.line_ids.due_date, date(2026, 11, 20))

    def test_due_date_before_invoice_date_is_reported(self):
        self.rule.write({"due_day": 5})
        batch = self._batch()
        batch.write({"invoice_date": date(2026, 11, 10)})
        batch.action_prepare()
        self.assertIn("error", batch.line_ids.mapped("status"))
        self.assertIn("anterior", batch.line_ids.message)

    def test_due_day_range_and_empty_fallback(self):
        for day in (32,):
            with self.assertRaises(ValidationError):
                self.rule.copy({"name": "Inválida %s" % day, "due_day": day})
        optional = self.rule.copy({"name": "Sin día propio", "due_day": False})
        self.assertFalse(optional.due_day)

    def test_future_rate_does_not_rewrite_existing_invoice_lines(self):
        batch = self._batch()
        batch.action_prepare()
        batch.with_user(self.finance).action_confirm()
        invoice_line = batch.line_ids.move_id.invoice_line_ids
        self.rule.write({"amount": 175})
        self.assertEqual(invoice_line.price_unit, 100)

    def test_company_isolation_and_reception_cannot_write_invoice(self):
        other_company = self.env["res.company"].create({"name": "Otra compañía prueba", "country_id": self.env.ref("base.do").id, "currency_id": self.dop.id})
        other_condo = self.env["kabay.condominium"].create({"name": "Otro condo", "code": "T-OTHER", "company_id": other_company.id})
        other_building = self.env["kabay.building"].create({"name": "Otra torre", "code": "T-OTHER-A", "condominium_id": other_condo.id})
        other_apartment = self.env["kabay.apartment"].create({"name": "Otro apto", "code": "T-OTHER-1", "building_id": other_building.id})
        other_rule = self.rule.copy({"name": "Otra cuota", "condominium_id": other_condo.id, "building_id": False, "apartment_ids": [(6, 0, [other_apartment.id])]})
        self.env["kabay.payment.responsibility"].create({"apartment_id": other_apartment.id, "fee_rule_id": other_rule.id,
            "partner_id": self.partner.id, "date_start": date(2026, 1, 1), "state": "confirmed"})
        other_batch = self.env["kabay.billing.batch"].create({"condominium_id": other_condo.id,
            "period_start": date(2026, 11, 1), "period_end": date(2026, 11, 30), "invoice_date": date(2026, 11, 1),
            "due_date": date(2026, 11, 15), "fee_rule_ids": [(6, 0, [other_rule.id])]})
        other_batch.action_prepare()
        self.assertEqual(other_batch.company_id, other_company)
        self.assertEqual(other_batch.line_ids.company_id, other_company)
        self.assertIn("error", other_batch.line_ids.mapped("status"))

        batch = self._batch()
        batch.action_prepare()
        batch.with_user(self.finance).action_confirm()
        invoice = batch.line_ids.move_id
        reception = self.env["res.users"].create({"name": "Recepción write test", "login": "kabay_reception_write_test",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id, self.env.ref("kabay_base.group_kabay_reception").id])]})
        with self.assertRaises(AccessError):
            invoice.with_user(reception).write({"ref": "no autorizado"})
