from odoo import api, fields, models


class KabayCondominium(models.Model):
    _name = "kabay.condominium"
    _description = "Condominium"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name, id"

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, copy=False, tracking=True)
    company_id = fields.Many2one(
        "res.company", string="Billing company", ondelete="restrict", tracking=True
    )
    manager_id = fields.Many2one("res.users", string="Manager", ondelete="set null")
    street = fields.Char()
    street2 = fields.Char()
    city = fields.Char()
    state_id = fields.Many2one("res.country.state", ondelete="restrict")
    zip = fields.Char()
    country_id = fields.Many2one("res.country", ondelete="restrict")
    building_ids = fields.One2many("kabay.building", "condominium_id", string="Buildings")
    building_count = fields.Integer(compute="_compute_structure_counts")
    apartment_count = fields.Integer(compute="_compute_structure_counts")
    active = fields.Boolean(default=True, tracking=True)
    notes = fields.Text()

    _code_uniq = models.Constraint(
        "unique(code)", "A condominium code must be unique."
    )

    @api.depends("building_ids", "building_ids.apartment_count")
    def _compute_structure_counts(self):
        for record in self:
            record.building_count = len(record.building_ids)
            record.apartment_count = sum(record.building_ids.mapped("apartment_count"))
