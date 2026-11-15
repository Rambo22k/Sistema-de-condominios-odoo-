from odoo import fields, models


class KabayApartment(models.Model):
    _inherit = "kabay.apartment"

    relation_ids = fields.One2many(
        "kabay.apartment.relation", "apartment_id", string="Personas"
    )
