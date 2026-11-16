{
    "name": "Kabay Facturación",
    "author": "Kabay Group",
    "summary": "Cuotas, responsabilidades y lotes de facturación de condominios",
    "version": "19.0.1.1.0",
    "category": "Accounting/Accounting",
    "license": "LGPL-3",
    "depends": ["base", "account", "contacts", "mail", "kabay_base", "kabay_residents"],
    "data": [
        "security/kabay_billing_security.xml",
        "security/ir.model.access.csv",
        "views/kabay_billing_views.xml",
    ],
    "application": True,
    "installable": True,
}
