{
    "name": "Kabay Solicitudes",
    "author": "Kabay Group",
    "summary": "Solicitudes residenciales sobre Helpdesk estándar de Odoo",
    "version": "19.0.1.0.0",
    "category": "Services/Condominium",
    "license": "LGPL-3",
    "depends": ["helpdesk", "portal", "kabay_base", "kabay_residents", "kabay_portal_ui"],
    "data": [
        "security/kabay_helpdesk_security.xml",
        "security/ir.model.access.csv",
        "data/kabay_helpdesk_category_data.xml",
        "views/kabay_helpdesk_views.xml",
        "views/portal_ticket_templates.xml",
    ],
    "post_init_hook": "post_init_hook",
    "application": False,
    "installable": True,
}
