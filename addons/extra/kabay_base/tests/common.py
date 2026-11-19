from odoo import Command


def setup_test_company_accounting(env, company):
    """Create isolated ledger objects required by Kabay flow tests."""
    accounts = env["account.account"].with_company(company).create([
        {
            "name": "QA Accounts Receivable", "code": "11010001",
            "account_type": "asset_receivable", "reconcile": True,
            "company_ids": [Command.set([company.id])],
        },
        {
            "name": "QA Accounts Payable", "code": "21010001",
            "account_type": "liability_payable", "reconcile": True,
            "company_ids": [Command.set([company.id])],
        },
        {
            "name": "QA Service Revenue", "code": "41020100",
            "account_type": "income", "company_ids": [Command.set([company.id])],
        },
        {
            "name": "QA Bank", "code": "11020001",
            "account_type": "asset_cash", "reconcile": True,
            "company_ids": [Command.set([company.id])],
        },
        {
            "name": "QA Outstanding Receipts", "code": "11030001",
            "account_type": "asset_current", "reconcile": True,
            "company_ids": [Command.set([company.id])],
        },
        {
            "name": "QA Outstanding Payments", "code": "11030002",
            "account_type": "asset_current", "reconcile": True,
            "company_ids": [Command.set([company.id])],
        },
        {
            "name": "QA Bank Suspense", "code": "11030003",
            "account_type": "asset_current", "reconcile": True,
            "company_ids": [Command.set([company.id])],
        },
    ])
    by_code = {account.code: account for account in accounts}
    sale_journal = env["account.journal"].with_company(company).create({
        "name": "Kabay QA Sales", "code": "KQSI", "type": "sale", "company_id": company.id,
    })
    bank_journal = env["account.journal"].with_company(company).create({
        "name": "Kabay QA Bank", "code": "KQBN", "type": "bank", "company_id": company.id,
        "default_account_id": by_code["11020001"].id,
        "suspense_account_id": by_code["11030003"].id,
    })
    if bank_journal.inbound_payment_method_line_ids:
        bank_journal.inbound_payment_method_line_ids[:1].payment_account_id = by_code["11030001"]
    if bank_journal.outbound_payment_method_line_ids:
        bank_journal.outbound_payment_method_line_ids[:1].payment_account_id = by_code["11030002"]
    return by_code, sale_journal, bank_journal


def create_kabay_test_company(env, name):
    reference_company = env.company
    company = env["res.company"].create({
        "name": name,
        "currency_id": reference_company.currency_id.id,
        "country_id": reference_company.country_id.id,
    })
    accounts, sale_journal, bank_journal = setup_test_company_accounting(env, company)
    return company, accounts, sale_journal, bank_journal


def set_test_partner_accounts(partner, company, accounts):
    partner.with_company(company).write({
        "property_account_receivable_id": accounts["11010001"].id,
        "property_account_payable_id": accounts["21010001"].id,
    })
