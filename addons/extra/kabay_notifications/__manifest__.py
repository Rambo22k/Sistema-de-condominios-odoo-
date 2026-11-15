{
    "name": "Kabay Notifications",
    "summary": "Comunicaciones automáticas seguras para residentes Kabay",
    "version": "19.0.1.0.0",
    "category": "Services/Condominium",
    "author": "Kabay Group",
    "license": "LGPL-3",
    "depends": [
        "mail", "account", "portal", "helpdesk", "kabay_base", "kabay_residents",
        "kabay_billing", "kabay_deposits", "kabay_financing", "kabay_notices",
        "kabay_helpdesk", "kabay_portal",
    ],
    "data": [
        "security/kabay_notifications_security.xml",
        "security/ir.model.access.csv",
        "data/kabay_notification_templates.xml",
        "data/kabay_notification_cron.xml",
        "views/kabay_notification_views.xml",
        "views/portal_notification_templates.xml",
    ],
    "post_init_hook": "post_init_hook",
    "application": True,
    "installable": True,
}
