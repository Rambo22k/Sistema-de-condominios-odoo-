from odoo import api, fields, models
from odoo.exceptions import ValidationError


class KabayBuilding(models.Model):
    _name = "kabay.building"
    _description = "Condominium building"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "condominium_id, name, id"

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, copy=False, tracking=True)
    condominium_id = fields.Many2one(
        "kabay.condominium", required=True, ondelete="restrict", index=True, tracking=True
    )
    company_id = fields.Many2one(
        "res.company", related="condominium_id.company_id", store=True, index=True
    )
    apartment_ids = fields.One2many("kabay.apartment", "building_id", string="Apartments")
    apartment_count = fields.Integer(compute="_compute_apartment_count")
    active = fields.Boolean(default=True, tracking=True)
    notes = fields.Text()

    _code_condominium_uniq = models.Constraint(
        "unique(code, condominium_id)", "A building code must be unique per condominium."
    )

    @api.depends("apartment_ids")
    def _compute_apartment_count(self):
        for record in self:
            record.apartment_count = len(record.apartment_ids)

    @api.constrains("condominium_id")
    def _check_condominium(self):
        if any(not record.condominium_id for record in self):
            raise ValidationError("Each building must belong to a condominium.")
