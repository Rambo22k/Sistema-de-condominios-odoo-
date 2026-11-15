from odoo import fields, models


class KabayHelpdeskCategory(models.Model):
    _name = "kabay.helpdesk.category"
    _description = "Kabay Helpdesk Category"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", index=True)

    _name_company_uniq = models.Constraint(
        "unique(name, company_id)", "Ya existe una categoría con ese nombre en esta compañía."
    )
