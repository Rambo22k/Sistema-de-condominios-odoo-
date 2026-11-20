from odoo import fields, models


class PortalWizardUser(models.TransientModel):
    _inherit = "portal.wizard.user"

    def action_grant_access(self):
        self.ensure_one()
        result = super().action_grant_access()

        partner = self.partner_id
        today = fields.Date.context_today(self)
        has_current_residence = self.env["kabay.apartment.relation"].sudo().search_count([
            ("partner_id", "=", partner.id),
            ("state", "=", "confirmed"),
            ("active", "=", True),
            ("date_start", "<=", today),
            "|", ("date_end", "=", False), ("date_end", ">=", today),
        ])
        if has_current_residence:
            user = partner.with_context(active_test=False).user_ids[:1].sudo()
            if user and user.has_group("base.group_portal") and not user.has_group("base.group_user"):
                resident_group = self.env.ref("kabay_deposits.group_kabay_deposit_resident")
                user.write({"group_ids": [(4, resident_group.id)]})
        return result
