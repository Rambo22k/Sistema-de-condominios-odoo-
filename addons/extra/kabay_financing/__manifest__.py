{
    "name": "Kabay Financiamiento",
    "author": "Kabay Group",
    "summary": "Contratos de compra financiada y calendarios de cuotas",
    "version": "19.0.1.2.0",
    "category": "Accounting/Accounting",
    "license": "LGPL-3",
    "depends": ["base", "account", "contacts", "mail", "kabay_base", "kabay_residents"],
    "data": [
        "security/kabay_financing_security.xml",
        "security/ir.model.access.csv",
        "data/financing_sequence.xml",
        "views/kabay_financing_views.xml",
    ],
    "application": True,
    "installable": True,
}
