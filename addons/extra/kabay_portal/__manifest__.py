{
    "name": "Portal de Residentes Kabay",
    "summary": "Portal Kabay unificado para residentes",
    "version": "19.0.1.1.0",
    "category": "Services/Condominium",
    "author": "Kabay Group",
    "license": "LGPL-3",
    "depends": [
        "portal", "kabay_portal_ui", "account", "kabay_base", "kabay_residents", "kabay_billing",
        "kabay_financing", "kabay_deposits", "kabay_notices", "kabay_helpdesk",
    ],
    "data": [
        "security/kabay_portal_security.xml",
        "security/ir.model.access.csv",
        "views/portal_templates.xml",
    ],
    "installable": True,
    "application": False,
}
