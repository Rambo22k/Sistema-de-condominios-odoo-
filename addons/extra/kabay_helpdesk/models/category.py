from odoo import fields, models


class KabayHelpdeskCategory(models.Model):
    _name = "kabay.helpdesk.category"
    _description = "Categoría de solicitudes Kabay"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True, string="Nombre")
    sequence = fields.Integer(default=10, string="Secuencia")
    active = fields.Boolean(default=True, string="Activo")
    company_id = fields.Many2one("res.company", index=True, string="Compañía")

    _name_company_uniq = models.Constraint(
        "unique(name, company_id)", "Ya existe una categoría con ese nombre en esta compañía."
    )
