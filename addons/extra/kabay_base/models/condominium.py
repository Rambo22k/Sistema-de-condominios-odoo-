from odoo import api, fields, models


class KabayCondominium(models.Model):
    _name = "kabay.condominium"
    _description = "Condominio"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name, id"

    name = fields.Char(string="Nombre", required=True, tracking=True)
    code = fields.Char(string="Código", required=True, copy=False, tracking=True)
    company_id = fields.Many2one(
        "res.company", string="Compañía de facturación", ondelete="restrict", tracking=True
    )
    manager_id = fields.Many2one("res.users", string="Administrador", ondelete="set null")
    street = fields.Char(string="Calle")
    street2 = fields.Char(string="Dirección adicional")
    city = fields.Char(string="Ciudad")
    state_id = fields.Many2one("res.country.state", string="Provincia", ondelete="restrict")
    zip = fields.Char(string="Código postal")
    country_id = fields.Many2one("res.country", string="País", ondelete="restrict")
    building_ids = fields.One2many("kabay.building", "condominium_id", string="Edificios")
    building_count = fields.Integer(compute="_compute_structure_counts", string="Cantidad de edificios")
    apartment_count = fields.Integer(compute="_compute_structure_counts", string="Cantidad de apartamentos")
    active = fields.Boolean(default=True, tracking=True, string="Activo")
    notes = fields.Text(string="Notas")

    _code_uniq = models.Constraint(
        "unique(code)", "El código del condominio debe ser único."
    )

    @api.depends("building_ids", "building_ids.apartment_count")
    def _compute_structure_counts(self):
        for record in self:
            record.building_count = len(record.building_ids)
            record.apartment_count = sum(record.building_ids.mapped("apartment_count"))
