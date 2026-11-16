{
    "name": "Portal de Residentes Kabay",
    "summary": "Portal Kabay unificado para residentes",
    "version": "19.0.1.0.0",
    "category": "Services/Condominium",
    "author": "Kabay Group",
    "license": "LGPL-3",
    "depends": [
        "portal", "account", "kabay_base", "kabay_residents", "kabay_billing",
        "kabay_financing", "kabay_deposits", "kabay_notices", "kabay_helpdesk",
    ],
    "data": [
        "security/kabay_portal_security.xml",
        "security/ir.model.access.csv",
        "views/portal_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": ["kabay_portal/static/src/css/kabay_portal.css"],
    },
    "installable": True,
    "application": False,
}
