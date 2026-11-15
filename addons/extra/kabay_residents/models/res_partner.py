from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    apartment_relation_ids = fields.One2many(
        "kabay.apartment.relation", "partner_id", string="Unidades relacionadas"
    )

    def action_add_apartment_relation(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Vincular con una unidad",
            "res_model": "kabay.apartment.relation",
            "view_mode": "form",
            "target": "current",
            "context": {"default_partner_id": self.id},
        }
