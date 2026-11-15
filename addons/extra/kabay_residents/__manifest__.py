{
    "name": "Kabay Residents",
    "author": "Kabay Group",
    "summary": "Relaciones históricas entre personas y apartamentos",
    "version": "19.0.1.0.0",
    "category": "Services/Condominium",
    "license": "LGPL-3",
    "depends": ["base", "contacts", "mail", "kabay_base"],
    "data": [
        "security/ir.model.access.csv",
        "security/kabay_residents_rules.xml",
        "views/kabay_relation_views.xml",
        "views/kabay_apartment_views.xml",
        "views/res_partner_views.xml",
        "views/kabay_menus.xml",
    ],
    "application": False,
    "installable": True,
}
