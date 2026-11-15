{
    "name": "Kabay Notices",
    "author": "Kabay Group",
    "summary": "Avisos comunitarios segmentados para residentes",
    "version": "19.0.1.0.0",
    "category": "Services/Condominium",
    "license": "LGPL-3",
    "depends": ["base", "mail", "contacts", "portal", "kabay_base", "kabay_residents"],
    "data": [
        "security/kabay_notices_security.xml",
        "security/ir.model.access.csv",
        "data/kabay_notice_sequence.xml",
        "data/kabay_notice_data.xml",
        "views/kabay_notice_views.xml",
        "views/portal_notice_templates.xml",
    ],
    "application": False,
    "installable": True,
}
