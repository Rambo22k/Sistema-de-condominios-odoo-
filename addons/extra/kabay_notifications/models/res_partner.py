from odoo import fields, models, _
from odoo.exceptions import AccessError


PREFERENCE_FIELDS = {
    "kabay_notify_invoice_reminders", "kabay_notify_ticket_updates",
    "kabay_notify_notices", "kabay_notify_financing_reminders",
}


class ResPartner(models.Model):
    _inherit = "res.partner"

    kabay_notify_invoice_reminders = fields.Boolean(default=True, string="Recordatorios de facturas")
    kabay_notify_ticket_updates = fields.Boolean(default=True, string="Actualizaciones de solicitudes")
    kabay_notify_notices = fields.Boolean(default=True, string="Avisos comunitarios")
    kabay_notify_financing_reminders = fields.Boolean(default=True, string="Recordatorios de cuotas")

    def write(self, vals):
        touched = PREFERENCE_FIELDS.intersection(vals)
        if touched and self.env.user.has_group("base.group_portal") and not self.env.is_system():
            if self != self.env.user.partner_id or set(vals) - PREFERENCE_FIELDS:
                raise AccessError(_("Solo puedes cambiar tus propias preferencias de comunicaciones."))
        elif touched and not self.env.is_system() and not self.env.user.has_group("kabay_base.group_kabay_manager"):
            raise AccessError(_("Solo el residente o Administración Kabay puede cambiar estas preferencias."))
        return super().write(vals)
