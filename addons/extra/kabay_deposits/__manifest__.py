{
    "name": "Kabay Deposits",
    "author": "Kabay Group",
    "summary": "Declaraciones de depósitos y aplicación contable verificada",
    "version": "19.0.1.0.0",
    "category": "Accounting/Accounting",
    "license": "LGPL-3",
    "depends": [
        "base", "account", "account_accountant", "contacts", "mail", "portal",
        "kabay_base", "kabay_residents", "kabay_billing", "kabay_financing",
    ],
    "data": [
        "security/kabay_deposits_security.xml",
        "security/ir.model.access.csv",
        "data/kabay_deposit_sequence.xml",
        "views/kabay_deposit_views.xml",
        "views/portal_deposit_templates.xml",
    ],
    "application": True,
    "installable": True,
}
