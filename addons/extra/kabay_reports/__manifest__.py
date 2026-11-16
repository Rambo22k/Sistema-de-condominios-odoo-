{
    "name": "Kabay Reportes",
    "author": "Kabay Group",
    "summary": "Panel y reportes operativos y financieros Kabay",
    "version": "19.0.1.0.0",
    "category": "Administration/Reporting",
    "license": "LGPL-3",
    "depends": [
        "account", "account_accountant", "helpdesk", "kabay_base", "kabay_residents",
        "kabay_billing", "kabay_financing", "kabay_deposits", "kabay_notices", "kabay_helpdesk",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/kabay_reports_views.xml",
    ],
    "application": False,
    "installable": True,
}
