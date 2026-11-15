from odoo import http, _
from odoo.exceptions import AccessError
from odoo.http import request


class KabayNotificationPortal(http.Controller):
    @http.route(
        "/my/kabay/notifications/preferences", type="http", auth="user",
        website=True, methods=["GET", "POST"],
    )
    def kabay_notification_preferences(self, **post):
        user = request.env.user
        if not user.has_group("base.group_portal") or user.has_group("base.group_user"):
            return request.redirect("/my/kabay")
        partner = user.partner_id
        saved = False
        error = False
        if request.httprequest.method == "POST":
            fields = {
                "kabay_notify_invoice_reminders": "invoice_reminders",
                "kabay_notify_ticket_updates": "ticket_updates",
                "kabay_notify_notices": "notices",
                "kabay_notify_financing_reminders": "financing_reminders",
            }
            values = {field: post.get(key) == "1" for field, key in fields.items()}
            try:
                partner.write(values)
                saved = True
            except AccessError:
                error = _("No se pudieron actualizar las preferencias de esta cuenta.")
        return request.render("kabay_notifications.portal_notification_preferences", {
            "partner": partner, "saved": saved, "error": error,
        })
