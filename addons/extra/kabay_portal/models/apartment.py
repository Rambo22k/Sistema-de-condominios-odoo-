from odoo import fields, models


class KabayApartment(models.Model):
    _inherit = "kabay.apartment"

    resident_relation_ids = fields.One2many(
        "kabay.apartment.relation", "apartment_id", string="Relaciones de residentes",
    )
