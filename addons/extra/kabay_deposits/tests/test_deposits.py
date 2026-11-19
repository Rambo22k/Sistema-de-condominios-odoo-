import base64
from datetime import date, timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.addons.kabay_base.tests.common import (
    create_kabay_test_company, set_test_partner_accounts, setup_test_company_accounting,
)


@tagged("post_install", "-at_install")
class TestKabayDeposits(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company, cls.accounts, cls.sales_journal, cls.bank_journal = create_kabay_test_company(
            cls.env, "Kabay Deposits Test Company",
        )
        cls.condominium = cls.env["kabay.condominium"].create({
            "name": "Condominio QA depósitos", "code": "DEP-QA", "company_id": cls.company.id,
            "country_id": cls.company.country_id.id,
        })
        cls.building = cls.env["kabay.building"].create({
            "name": "Torre QA depósitos", "code": "DEP-QA-A", "condominium_id": cls.condominium.id,
        })
        cls.apartment = cls.env["kabay.apartment"].create({
            "name": "QA-01", "code": "DEP-QA-01", "building_id": cls.building.id,
        })
        cls.partner = cls.env["res.partner"].create({"name": "Residente QA depósitos", "company_type": "person"})
        cls.other_partner = cls.env["res.partner"].create({"name": "Otro residente QA depósitos", "company_type": "person"})
        set_test_partner_accounts(cls.partner, cls.company, cls.accounts)
        set_test_partner_accounts(cls.other_partner, cls.company, cls.accounts)
        cls.relation = cls.env["kabay.apartment.relation"].create({
            "partner_id": cls.partner.id, "apartment_id": cls.apartment.id, "role": "owner",
            "date_start": date(2020, 1, 1), "state": "confirmed",
        })
        cls.apartment2 = cls.env["kabay.apartment"].create({
            "name": "QA-02", "code": "DEP-QA-02", "building_id": cls.building.id,
        })
        cls.other_relation = cls.env["kabay.apartment.relation"].create({
            "partner_id": cls.other_partner.id, "apartment_id": cls.apartment2.id, "role": "tenant",
            "date_start": date(2020, 1, 1), "state": "confirmed",
        })
        cls.income_account = cls.accounts["41020100"]
        cls.product = cls.env["product.product"].with_company(cls.company).create({
            "name": "Servicio QA depósitos", "type": "service",
            "property_account_income_id": cls.income_account.id,
            "taxes_id": [(5, 0, 0)],
        })
        cls.finance = cls.env["res.users"].create({
            "name": "Finanzas QA depósitos", "login": "kabay_deposit_finance_test",
            "company_id": cls.company.id, "company_ids": [(6, 0, [cls.company.id])],
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("account.group_account_invoice").id,
                cls.env.ref("account.group_account_user").id,
                cls.env.ref("kabay_base.group_kabay_finance").id,
            ])],
        })
        cls.portal_user = cls.env["res.users"].create({
            "name": "Portal QA depósitos", "login": "kabay_deposit_portal_test", "partner_id": cls.partner.id,
            "company_id": cls.company.id, "company_ids": [(6, 0, [cls.company.id])],
            "group_ids": [(6, 0, [cls.env.ref("kabay_deposits.group_kabay_deposit_resident").id])],
        })
        cls.other_portal_user = cls.env["res.users"].create({
            "name": "Otro portal QA depósitos", "login": "kabay_deposit_portal_other_test", "partner_id": cls.other_partner.id,
            "company_id": cls.company.id, "company_ids": [(6, 0, [cls.company.id])],
            "group_ids": [(6, 0, [cls.env.ref("kabay_deposits.group_kabay_deposit_resident").id])],
        })
        cls.reception = cls.env["res.users"].create({
            "name": "Recepción QA depósitos", "login": "kabay_deposit_reception_test",
            "company_id": cls.company.id, "company_ids": [(6, 0, [cls.company.id])],
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id, cls.env.ref("kabay_base.group_kabay_reception").id])],
        })
        cls.maintenance = cls.env["res.users"].create({
            "name": "Mantenimiento QA depósitos", "login": "kabay_deposit_maintenance_test",
            "company_id": cls.company.id, "company_ids": [(6, 0, [cls.company.id])],
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id, cls.env.ref("kabay_base.group_kabay_maintenance").id])],
        })

    def _invoice(self, amount=100, apartment=None, partner=None, company=None, financing=False):
        apartment = apartment or self.apartment
        partner = partner or self.partner
        company = company or self.company
        if company == self.company:
            accounts = self.accounts
            sales_journal = self.sales_journal
        else:
            accounts, sales_journal, _bank_journal = setup_test_company_accounting(self.env, company)
            set_test_partner_accounts(partner, company, accounts)
        journal = sales_journal
        account = accounts["41020100"]
        values = {
            "move_type": "out_invoice", "company_id": company.id, "journal_id": journal.id,
            "partner_id": partner.id, "invoice_date": fields.Date.context_today(self),
            "invoice_date_due": fields.Date.context_today(self) + timedelta(days=15),
            "invoice_line_ids": [Command.create({
                "name": "Cargo QA depósito", "quantity": 1, "price_unit": amount,
                "account_id": account.id, "tax_ids": [Command.clear()],
            })],
        }
        # A foreign-company invoice in the cross-company rejection test is an
        # ordinary invoice, not an invalid Kabay invoice tied to this apartment.
        if apartment.company_id == company:
            values.update({"kabay_apartment_id": apartment.id, "kabay_responsible_id": partner.id})
        invoice = self.env["account.move"].with_company(company).create(values)
        invoice.action_post()
        if financing:
            invoice.write({
                "kabay_apartment_id": False, "kabay_responsible_id": False,
                "kabay_financing_apartment_id": apartment.id,
            })
        return invoice

    def _declaration(self, amount=100, invoice=None, apartment=None, partner=None, reference="REF-DEP-001", deposit_date=None, user=None, allocations=None):
        apartment = apartment or self.apartment
        partner = partner or self.partner
        if allocations is None and invoice:
            allocations = [(0, 0, {"invoice_id": invoice.id, "amount": amount})]
        values = {
            "apartment_id": apartment.id,
            "declarant_partner_id": partner.id,
            "deposit_date": deposit_date or fields.Date.context_today(self),
            "amount": amount,
            "bank_name": "Banco QA",
            "reference": reference,
            "proof": base64.b64encode(b"comprobante QA"),
            "proof_filename": "comprobante.pdf",
            "allocation_ids": allocations or [],
        }
        return self.env["kabay.deposit.declaration"].with_user(user or self.portal_user).create(values)

    def _statement_line(self, amount=100, reference="REF-DEP-001", date_value=None, partner=None):
        return self.env["account.bank.statement.line"].with_user(self.finance).create({
            "journal_id": self.bank_journal.id,
            "date": date_value or fields.Date.context_today(self),
            "amount": amount,
            "payment_ref": "Transferencia bancaria %s" % reference,
            "partner_id": (partner or self.partner).id,
        })

    def _verify(self, declaration, statement_line):
        declaration.with_user(self.portal_user).action_submit()
        finance_declaration = declaration.with_user(self.finance)
        finance_declaration.action_start_review()
        finance_declaration.write({"statement_line_id": statement_line.id})
        finance_declaration.action_verify_bank_line()
        return finance_declaration

    def _financing_invoice(self, apartment=None, partner=None, amount=100):
        apartment = apartment or self.apartment
        partner = partner or self.partner
        contract = self.env["kabay.financing.contract"].create({
            "condominium_id": apartment.condominium_id.id,
            "apartment_id": apartment.id,
            "buyer_id": partner.id,
            "creditor_id": self.env["res.partner"].create({"name": "Acreedor QA depósitos"}).id,
            "company_id": apartment.company_id.id,
            "currency_id": apartment.company_id.currency_id.id,
            "product_id": self.product.id,
            "purchase_price": amount,
            "down_payment": 0,
            "installment_count": 1,
            "frequency": "monthly",
            "interest_rate": 0,
            "start_date": fields.Date.context_today(self),
        })
        contract.action_confirm()
        installment = contract.installment_ids
        installment.with_user(self.finance).action_generate_invoice()
        invoice = installment.invoice_id.with_user(self.finance)
        invoice.action_post()
        return contract, installment, invoice

    def test_01_create_valid_portal_declaration(self):
        invoice = self._invoice(100)
        declaration = self._declaration(100, invoice)
        declaration.with_user(self.portal_user).action_submit()
        self.assertEqual(declaration.state, "submitted")
        self.assertEqual(declaration.declarant_partner_id, self.partner)
        self.assertEqual(declaration.company_id, self.company)
        self.assertEqual(declaration.currency_id, self.company.currency_id)

    def test_02_reject_zero_or_negative_amount(self):
        invoice = self._invoice(100)
        for amount in (0, -1):
            with self.assertRaises(UserError):
                self._declaration(amount, invoice, reference="REF-ZERO-%s" % amount)

    def test_03_reject_apartment_without_current_resident_authorization(self):
        invoice = self._invoice(100, apartment=self.apartment2, partner=self.other_partner)
        with self.assertRaises(UserError):
            self._declaration(100, invoice, apartment=self.apartment2)

    def test_04_reject_invoice_from_another_company(self):
        other_company = self.env.company
        if other_company == self.company:
            other_company = self.env["res.company"].search([("id", "!=", self.company.id)], limit=1)
        if not other_company:
            other_company = self.env["res.company"].create({"name": "Compañía QA depósito externa"})
        invoice = self._invoice(100, company=other_company)
        with self.assertRaises(UserError):
            self._declaration(100, invoice)

    def test_05_reject_cancelled_invoice(self):
        invoice = self._invoice(100)
        invoice.button_cancel()
        with self.assertRaises(UserError):
            self._declaration(100, invoice)

    def test_06_reject_incompatible_financing_contract_installment(self):
        _, installment, invoice = self._financing_invoice(apartment=self.apartment2, partner=self.other_partner)
        with self.assertRaises(UserError):
            self._declaration(100, invoice, allocations=[(0, 0, {
                "invoice_id": invoice.id, "installment_id": installment.id, "amount": 100,
            })])

    def test_07_prevent_duplicate_declaration(self):
        invoice = self._invoice(200)
        first = self._declaration(100, invoice, reference="DUP-100", allocations=[(0, 0, {"invoice_id": invoice.id, "amount": 100})])
        first.with_user(self.portal_user).action_submit()
        second = self._declaration(100, invoice, reference="DUP-100", allocations=[(0, 0, {"invoice_id": invoice.id, "amount": 100})])
        with self.assertRaises(ValidationError):
            second.with_user(self.portal_user).action_submit()

    def test_08_declaration_does_not_create_payment_or_change_invoice_balance(self):
        invoice = self._invoice(100)
        before_residual = invoice.amount_residual
        before_payment_count = self.env["account.payment"].search_count([("partner_id", "=", self.partner.id)])
        declaration = self._declaration(50, invoice, allocations=[(0, 0, {"invoice_id": invoice.id, "amount": 50})])
        self.assertEqual(declaration.state, "draft")
        self.assertFalse(declaration.allocation_ids.payment_id)
        self.assertEqual(invoice.amount_residual, before_residual)
        self.assertEqual(self.env["account.payment"].search_count([("partner_id", "=", self.partner.id)]), before_payment_count)

    def test_09_proof_is_private_to_declarant(self):
        invoice = self._invoice(100)
        declaration = self._declaration(100, invoice)
        attachment = self.env["ir.attachment"].search([
            ("res_model", "=", "kabay.deposit.declaration"), ("res_id", "=", declaration.id), ("res_field", "=", "proof"),
        ], limit=1)
        self.assertTrue(attachment)
        self.assertFalse(attachment.public)
        with self.assertRaises(AccessError):
            declaration.with_user(self.other_portal_user).read(["name"])
        with self.assertRaises(AccessError):
            attachment.with_user(self.other_portal_user).read(["name"])

    def test_10_reception_cannot_apply_payment(self):
        invoice = self._invoice(100)
        declaration = self._declaration(100, invoice)
        declaration._transition({"state": "verified"})
        with self.assertRaises(AccessError):
            declaration.with_user(self.reception).action_apply()

    def test_11_maintenance_cannot_read_declarations_or_financial_information(self):
        with self.assertRaises(AccessError):
            self.env["kabay.deposit.declaration"].with_user(self.maintenance).search_count([])
        with self.assertRaises(AccessError):
            self.env["kabay.deposit.allocation"].with_user(self.maintenance).search_count([])

    def test_12_verify_only_against_real_matching_bank_statement_line(self):
        invoice = self._invoice(100)
        declaration = self._declaration(100, invoice)
        statement_line = self._statement_line(100)
        before_residual = invoice.amount_residual
        before_payments = self.env["account.payment"].search_count([("partner_id", "=", self.partner.id)])
        verified = self._verify(declaration, statement_line)
        self.assertEqual(verified.state, "verified")
        self.assertFalse(verified.allocation_ids.payment_id)
        self.assertEqual(invoice.amount_residual, before_residual)
        self.assertEqual(self.env["account.payment"].search_count([("partner_id", "=", self.partner.id)]), before_payments)

    def test_13_reject_missing_or_mismatching_bank_movement_and_reference(self):
        invoice = self._invoice(100)
        declaration = self._declaration(100, invoice)
        declaration.with_user(self.portal_user).action_submit()
        finance_declaration = declaration.with_user(self.finance)
        finance_declaration.action_start_review()
        with self.assertRaises(ValidationError):
            finance_declaration.action_verify_bank_line()
        bad_line = self._statement_line(99, reference="OTHER-REF")
        with self.assertRaises(ValidationError):
            finance_declaration.write({"statement_line_id": bad_line.id})

    def test_14_prevent_reusing_a_bank_movement(self):
        invoice = self._invoice(200)
        today = fields.Date.context_today(self)
        statement_line = self._statement_line(100, reference="DUP-BANK", date_value=today)
        first = self._declaration(100, invoice, reference="DUP-BANK", deposit_date=today, allocations=[(0, 0, {"invoice_id": invoice.id, "amount": 100})])
        self._verify(first, statement_line)
        second = self._declaration(100, invoice, reference="DUP-BANK", deposit_date=today - timedelta(days=1), allocations=[(0, 0, {"invoice_id": invoice.id, "amount": 100})])
        second.with_user(self.portal_user).action_submit()
        second_finance = second.with_user(self.finance)
        second_finance.action_start_review()
        with self.assertRaises(ValidationError):
            second_finance.write({"statement_line_id": statement_line.id})

    def test_15_apply_partial_payment_through_standard_wizard(self):
        invoice = self._invoice(100)
        statement_line = self._statement_line(40, reference="PARTIAL-40")
        declaration = self._declaration(40, invoice, reference="PARTIAL-40", allocations=[(0, 0, {"invoice_id": invoice.id, "amount": 40})])
        verified = self._verify(declaration, statement_line)
        verified.action_apply()
        invoice.invalidate_recordset(["payment_state", "amount_residual"])
        self.assertEqual(verified.state, "applied")
        self.assertEqual(len(verified.payment_ids), 1)
        self.assertTrue(statement_line.is_reconciled)
        self.assertEqual(invoice.amount_residual, 60)
        self.assertIn(invoice.payment_state, ("partial", "in_payment"))

    def test_16_apply_one_deposit_to_multiple_invoices(self):
        invoice1 = self._invoice(40)
        invoice2 = self._invoice(60)
        statement_line = self._statement_line(100, reference="MULTI-100")
        declaration = self._declaration(100, invoice1, reference="MULTI-100", allocations=[
            (0, 0, {"invoice_id": invoice1.id, "amount": 40}),
            (0, 0, {"invoice_id": invoice2.id, "amount": 60}),
        ])
        verified = self._verify(declaration, statement_line)
        verified.action_apply()
        self.assertEqual(verified.state, "applied")
        self.assertEqual(len(verified.payment_ids), 2)
        self.assertTrue(statement_line.is_reconciled)
        self.assertEqual(invoice1.payment_state, "paid")
        self.assertEqual(invoice2.payment_state, "paid")

    def test_17_full_payment_is_reconciled_by_odoo(self):
        invoice = self._invoice(100)
        statement_line = self._statement_line(100, reference="FULL-100")
        declaration = self._declaration(100, invoice, reference="FULL-100")
        verified = self._verify(declaration, statement_line)
        verified.action_apply()
        invoice.invalidate_recordset(["payment_state", "amount_residual"])
        self.assertEqual(invoice.payment_state, "paid")
        self.assertEqual(invoice.amount_residual, 0)
        self.assertTrue(verified.allocation_ids.payment_id.is_reconciled)
        self.assertTrue(statement_line.is_reconciled)

    def test_18_applied_declaration_and_allocations_cannot_be_edited(self):
        invoice = self._invoice(100)
        statement_line = self._statement_line(100, reference="LOCK-100")
        declaration = self._declaration(100, invoice, reference="LOCK-100")
        verified = self._verify(declaration, statement_line)
        verified.action_apply()
        with self.assertRaises(UserError):
            verified.write({"resident_note": "Cambio posterior"})
        with self.assertRaises(UserError):
            verified.allocation_ids.write({"amount": 99})

    def test_19_finance_record_rules_isolate_companies(self):
        other_company = self.env["res.company"].search([("id", "!=", self.company.id)], limit=1)
        if not other_company:
            other_company = self.env["res.company"].create({"name": "Compañía QA regla depósitos"})
        condo = self.env["kabay.condominium"].create({"name": "Condo aislado", "code": "DEP-OTHER", "company_id": other_company.id})
        building = self.env["kabay.building"].create({"name": "Torre aislada", "code": "DEP-OTHER-A", "condominium_id": condo.id})
        apartment = self.env["kabay.apartment"].create({"name": "Unidad aislada", "code": "DEP-OTHER-01", "building_id": building.id})
        self.env["kabay.apartment.relation"].create({
            "partner_id": self.partner.id, "apartment_id": apartment.id, "role": "owner",
            "date_start": date(2020, 1, 1), "state": "confirmed",
        })
        invoice = self._invoice(1, apartment=apartment, partner=self.partner, company=other_company)
        declaration = self.env["kabay.deposit.declaration"].with_company(other_company).create({
            "apartment_id": apartment.id, "declarant_partner_id": self.partner.id,
            "deposit_date": fields.Date.context_today(self), "amount": 1,
            "bank_name": "Otro banco", "reference": "OTHER-COMPANY",
            "proof": base64.b64encode(b"QA"),
            "allocation_ids": [(0, 0, {"invoice_id": invoice.id, "amount": 1})],
        })
        self.assertFalse(self.env["kabay.deposit.declaration"].with_user(self.finance).search([("id", "=", declaration.id)]))

    def test_20_audit_transitions_record_actor_and_reject_reason(self):
        invoice = self._invoice(100)
        declaration = self._declaration(100, invoice)
        with self.assertRaises(UserError):
            declaration.write({"state": "verified"})
        declaration.with_user(self.portal_user).action_submit()
        reviewing = declaration.with_user(self.finance)
        reviewing.action_start_review()
        self.assertEqual(reviewing.state, "reviewing")
        self.assertEqual(reviewing.reviewer_id, self.finance)
        self.assertTrue(reviewing.reviewed_at)
        reviewing.action_reject("No coincide con el movimiento bancario")
        self.assertEqual(reviewing.state, "rejected")
        self.assertEqual(reviewing.rejected_by_id, self.finance)
        self.assertEqual(reviewing.rejection_reason, "No coincide con el movimiento bancario")
        self.assertTrue(reviewing.rejected_at)
