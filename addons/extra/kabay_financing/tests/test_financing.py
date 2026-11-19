from datetime import date
from types import SimpleNamespace

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.addons.kabay_base.tests.common import create_kabay_test_company, set_test_partner_accounts


@tagged("post_install", "-at_install")
class TestKabayFinancing(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company, cls.accounts, cls.sale_journal, cls.bank_journal = create_kabay_test_company(
            cls.env, "Kabay Financing Test Company",
        )
        cls.condominium = cls.env["kabay.condominium"].create({
            "name": "Condominio test financiamiento", "code": "T-FIN", "company_id": cls.company.id,
            "country_id": cls.company.country_id.id,
        })
        cls.building = cls.env["kabay.building"].create({"name": "Torre test financiamiento", "code": "TF-1", "condominium_id": cls.condominium.id})
        cls.apartment = cls.env["kabay.apartment"].create({"name": "F-01", "code": "TF-A01", "building_id": cls.building.id})
        cls.buyer = cls.env["res.partner"].create({"name": "Comprador test financiamiento"})
        cls.creditor = cls.env["res.partner"].create({"name": "Acreedor test financiamiento"})
        set_test_partner_accounts(cls.buyer, cls.company, cls.accounts)
        set_test_partner_accounts(cls.creditor, cls.company, cls.accounts)
        cls.income_account = cls.accounts["41020100"]
        cls.sale_tax = cls.company.account_sale_tax_id
        cls.product = cls.env["product.product"].with_company(cls.company).create({
            "name": "Producto servicio test financiamiento", "type": "service",
            "property_account_income_id": cls.income_account.id,
            "taxes_id": [(6, 0, cls.sale_tax.ids)],
        })
        cls.finance = cls.env["res.users"].create({
            "name": "Finanzas Test Financiamiento", "login": "kabay_finance_financing_test",
            "company_id": cls.company.id, "company_ids": [(6, 0, [cls.company.id])],
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id, cls.env.ref("kabay_base.group_kabay_finance").id])],
        })
        cls.manager = cls.env["res.users"].create({
            "name": "Administración Test Financiamiento", "login": "kabay_manager_financing_test",
            "company_id": cls.company.id, "company_ids": [(6, 0, [cls.company.id])],
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id, cls.env.ref("kabay_base.group_kabay_manager").id])],
        })
        cls.reception = cls.env["res.users"].create({
            "name": "Recepción Test Financiamiento", "login": "kabay_reception_financing_test",
            "company_id": cls.company.id, "company_ids": [(6, 0, [cls.company.id])],
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id, cls.env.ref("kabay_base.group_kabay_reception").id])],
        })

    def _contract(self, **overrides):
        values = {
            "condominium_id": self.condominium.id,
            "apartment_id": self.apartment.id,
            "buyer_id": self.buyer.id,
            "creditor_id": self.creditor.id,
            "company_id": self.company.id,
            "currency_id": self.company.currency_id.id,
            "product_id": self.product.id,
            "purchase_price": 3_000_000,
            "down_payment": 600_000,
            "installment_count": 60,
            "frequency": "monthly",
            "interest_rate": 0,
            "start_date": date(2026, 12, 1),
            "invoice_lead_days": 30,
        }
        values.update(overrides)
        return self.env["kabay.financing.contract"].create(values)

    def test_price_down_payment_and_financed_balance(self):
        contract = self._contract()
        self.assertEqual(contract.financed_amount, 2_400_000)
        self.assertEqual(contract.installment_amount, 40_000)
        with self.assertRaises(ValidationError):
            self._contract(down_payment=3_000_000)

    def test_generate_sixty_monthly_installments_once(self):
        contract = self._contract()
        contract.action_confirm()
        self.assertEqual(contract.state, "active")
        self.assertEqual(len(contract.installment_ids), 60)
        self.assertEqual(contract.installment_ids.mapped("number"), list(range(1, 61)))
        self.assertEqual(set(contract.installment_ids.mapped("capital_amount")), {40_000})
        self.assertEqual(sum(contract.installment_ids.mapped("capital_amount")), 2_400_000)
        self.assertEqual(contract.installment_ids[0].due_date, date(2026, 12, 1))
        self.assertEqual(contract.installment_ids[-1].due_date, date(2031, 11, 1))
        self.assertFalse(contract.installment_ids.mapped("invoice_id"))

    def test_installments_cannot_be_created_by_forging_context(self):
        contract = self._contract(installment_count=1, purchase_price=100, down_payment=0)
        with self.assertRaises(AccessError):
            self.env["kabay.financing.installment"].with_user(self.manager).with_context(
                kabay_financing_schedule=True,
            ).create({
                "contract_id": contract.id, "number": 1, "due_date": date(2026, 12, 1),
                "capital_amount": 100, "interest_amount": 0,
            })
        self.assertFalse(contract.installment_ids)

    def test_only_administration_can_confirm_a_contract(self):
        contract = self._contract(installment_count=1, purchase_price=100, down_payment=0)
        with self.assertRaises(UserError):
            contract.with_user(self.manager).write({"state": "active"})
        with self.assertRaises(AccessError):
            contract.with_user(self.finance).action_confirm()
        self.assertEqual(contract.state, "draft")
        contract.with_user(self.manager).action_confirm()
        self.assertEqual(contract.state, "active")

    def test_financing_invoice_link_rejects_another_company(self):
        contract = self._contract(installment_count=1, purchase_price=100, down_payment=0)
        contract.action_confirm()
        line = contract.installment_ids
        other_company = self.env["res.company"].create({"name": "Otra compañía para validar factura"})
        forged_invoice = SimpleNamespace(
            ensure_one=lambda: None, state="draft", move_type="out_invoice",
            company_id=other_company, currency_id=contract.currency_id,
            partner_id=contract.buyer_id, kabay_financing_contract_id=contract,
            kabay_financing_installment_id=line, kabay_financing_apartment_id=contract.apartment_id,
            kabay_financing_creditor_id=contract.creditor_id,
        )
        with self.assertRaises(ValidationError):
            line._check_invoice_identity(forged_invoice)
        contract.action_confirm()
        self.assertEqual(len(contract.installment_ids), 1)
        self.assertFalse(contract.installment_ids.mapped("invoice_id"))

    def test_short_months_leap_year_and_quarterly_schedule(self):
        monthly = self._contract(installment_count=3, start_date=date(2027, 1, 31), due_day=31, purchase_price=300, down_payment=0)
        monthly.action_confirm()
        self.assertEqual(monthly.installment_ids.mapped("due_date"), [date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31)])
        leap = self._contract(installment_count=2, start_date=date(2028, 1, 31), due_day=31, purchase_price=200, down_payment=0)
        leap.action_confirm()
        self.assertEqual(leap.installment_ids.mapped("due_date"), [date(2028, 1, 31), date(2028, 2, 29)])
        quarterly = self._contract(installment_count=3, start_date=date(2027, 1, 31), due_day=31, frequency="quarterly", purchase_price=300, down_payment=0)
        quarterly.action_confirm()
        self.assertEqual(quarterly.installment_ids.mapped("due_date"), [date(2027, 1, 31), date(2027, 4, 30), date(2027, 7, 31)])

    def test_interest_rate_calculates_amortized_schedule_and_method_automatically(self):
        contract = self._contract(interest_rate=5)
        self.assertIn("Amortización francesa", contract.interest_method)
        self.assertGreater(contract.installment_amount, 40_000)
        contract.action_confirm()
        self.assertEqual(contract.state, "active")
        self.assertEqual(len(contract.installment_ids), 60)
        self.assertEqual(contract.installment_ids[0].interest_amount, 10_000)
        self.assertAlmostEqual(sum(contract.installment_ids.mapped("capital_amount")), 2_400_000, places=2)
        self.assertGreater(sum(contract.installment_ids.mapped("interest_amount")), 0)

    def test_invoice_draft_is_individual_and_idempotent(self):
        contract = self._contract()
        contract.action_confirm()
        first = contract.installment_ids[0]
        first.with_user(self.finance).action_generate_invoice()
        invoice = first.invoice_id
        self.assertEqual(invoice.state, "draft")
        self.assertEqual(invoice.move_type, "out_invoice")
        self.assertEqual(invoice.company_id, self.company)
        self.assertEqual(invoice.currency_id, self.company.currency_id)
        self.assertEqual(invoice.partner_id, self.buyer)
        self.assertEqual(invoice.kabay_financing_contract_id, contract)
        self.assertEqual(invoice.kabay_financing_installment_id, first)
        self.assertEqual(invoice.kabay_financing_apartment_id, self.apartment)
        self.assertEqual(invoice.kabay_financing_creditor_id, self.creditor)
        self.assertEqual(invoice.invoice_date_due, first.due_date)
        self.assertEqual(invoice.invoice_line_ids.product_id, self.product)
        self.assertEqual(invoice.invoice_line_ids.account_id, self.income_account)
        self.assertEqual(invoice.invoice_line_ids.price_unit, 40_000)
        self.assertEqual(invoice.invoice_line_ids.tax_ids, self.sale_tax)
        with self.assertRaises(UserError):
            first.with_user(self.finance).action_generate_invoice()
        second = contract.installment_ids[1]
        with self.assertRaises(UserError):
            second.with_user(self.finance).with_context(kabay_financing_link_invoice=True).write({"invoice_id": invoice.id})
        self.assertEqual(self.env["account.move"].search_count([("kabay_financing_installment_id", "=", first.id)]), 1)

    def test_cancel_preserves_existing_invoice_and_cancels_only_future_schedule(self):
        contract = self._contract(installment_count=2, purchase_price=80_000, down_payment=0)
        contract.action_confirm()
        first, second = contract.installment_ids
        first.with_user(self.finance).action_generate_invoice()
        invoice = first.invoice_id
        contract.action_cancel()
        self.assertEqual(invoice.state, "draft")
        self.assertEqual(first.state, "draft")
        self.assertEqual(second.state, "cancelled")

    def test_partial_and_fully_reconciled_payment_states(self):
        contract = self._contract(installment_count=1, purchase_price=40_000, down_payment=0)
        contract.action_confirm()
        installment = contract.installment_ids
        installment.with_user(self.finance).action_generate_invoice()
        invoice = installment.invoice_id.with_user(self.finance)
        invoice.action_post()
        pay_ctx = {"active_model": "account.move", "active_ids": invoice.ids}
        half_payment = self.env["account.payment.register"].with_user(self.finance).with_context(**pay_ctx).create({"amount": 20_000})
        half_payment._create_payments()
        invoice.invalidate_recordset()
        self.assertIn(invoice.payment_state, ("partial", "in_payment"))
        self.assertEqual(installment.state, "partial")
        self.assertEqual(contract.paid_installments, 0)
        remainder = self.env["account.payment.register"].with_user(self.finance).with_context(**pay_ctx).create({"amount": invoice.amount_residual})
        remainder._create_payments()
        invoice.invalidate_recordset()
        self.assertEqual(invoice.payment_state, "paid")
        self.assertEqual(installment.state, "paid")
        self.assertEqual(contract.paid_installments, 1)

    def test_progress_twenty_of_sixty_uses_reconciled_accounting_state(self):
        contract = self._contract()
        contract.action_confirm()
        first_twenty = contract.installment_ids[:20]
        first_twenty.with_user(self.finance)._create_draft_invoices()
        invoices = first_twenty.mapped("invoice_id").with_user(self.finance)
        invoices.action_post()
        register = self.env["account.payment.register"].with_user(self.finance).with_context(
            active_model="account.move", active_ids=invoices.ids,
        ).create({"group_payment": True})
        register._create_payments()
        invoices.invalidate_recordset()
        self.assertTrue(all(invoice.payment_state == "paid" for invoice in invoices))
        self.assertEqual(contract.paid_installments, 20)
        self.assertEqual(contract.progress_label, "20 / 60")

    def test_manual_generation_only_creates_drafts_and_reexecution_does_not_duplicate(self):
        today = date.today()
        contract = self._contract(installment_count=2, start_date=today, due_day=today.day, purchase_price=80_000, down_payment=0, invoice_lead_days=0)
        contract.action_confirm()
        contract.with_user(self.finance).action_generate_invoices()
        invoice_count = self.env["account.move"].search_count([("kabay_financing_contract_id", "=", contract.id)])
        self.assertEqual(invoice_count, 1)
        invoice = contract.invoice_ids
        self.assertEqual(invoice.state, "draft")
        contract.with_user(self.finance).action_generate_invoices()
        self.assertEqual(self.env["account.move"].search_count([("kabay_financing_contract_id", "=", contract.id)]), 1)
        self.assertEqual(invoice.state, "draft")

    def test_group_payment_requires_common_contract_buyer_company_currency(self):
        contract = self._contract(installment_count=2, purchase_price=80_000, down_payment=0)
        contract.action_confirm()
        lines = contract.installment_ids
        lines.with_user(self.finance)._create_draft_invoices()
        invoices = lines.mapped("invoice_id").with_user(self.finance)
        invoices.action_post()
        result = lines.with_user(self.finance).action_validate_payment_group()
        self.assertEqual(result["tag"], "display_notification")
        other_contract = self._contract(installment_count=1, purchase_price=40_000, down_payment=0)
        other_contract.action_confirm()
        other_line = other_contract.installment_ids
        other_line.with_user(self.finance)._create_draft_invoices()
        other_line.invoice_id.with_user(self.finance).action_post()
        with self.assertRaises(UserError):
            (lines[:1] | other_line).with_user(self.finance).action_validate_payment_group()

    def test_suspended_contract_does_not_generate_and_finance_only_can_invoice(self):
        contract = self._contract(installment_count=2, purchase_price=80_000, down_payment=0)
        contract.action_confirm()
        contract.action_suspend()
        with self.assertRaises(UserError):
            contract.with_user(self.finance).action_generate_invoices()
        with self.assertRaises(UserError):
            contract.installment_ids[0].with_user(self.reception).action_generate_invoice()

    def test_reception_can_read_contract_progress_without_accounting_access(self):
        contract = self._contract(installment_count=1, purchase_price=40_000, down_payment=0)
        contract.action_confirm()
        contract.installment_ids.with_user(self.finance)._create_draft_invoices()
        reception_contract = contract.with_user(self.reception)
        self.assertEqual(reception_contract.progress_label, "0 / 1")
        self.assertEqual(reception_contract.draft_installments, 1)
        self.assertEqual(reception_contract.installment_ids.state, "draft")
        with self.assertRaises(AccessError):
            contract.installment_ids.invoice_id.with_user(self.reception).read(["name"])

    def test_future_terms_are_locked_after_activation(self):
        contract = self._contract()
        contract.action_confirm()
        with self.assertRaises(UserError):
            contract.write({"purchase_price": 4_000_000})
