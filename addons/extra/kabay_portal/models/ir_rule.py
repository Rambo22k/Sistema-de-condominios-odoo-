from odoo import fields, models


class IrRule(models.Model):
    _inherit = "ir.rule"

    def _eval_context(self):
        context = super()._eval_context()
        context["kabay_today"] = fields.Date.to_string(fields.Date.context_today(self))
        return context
