from datetime import timedelta
from html import escape
import logging

import psycopg2
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from markupsafe import Markup
from odoo.tools import html_sanitize


_logger = logging.getLogger(__name__)

EVENTS = [
    ("invoice_posted", "Factura Kabay publicada"),
    ("credit_note_posted", "Nota de crédito publicada"),
    ("invoice_reminder", "Recordatorio de vencimiento"),
    ("deposit_submitted", "Depósito declarado"),
    ("deposit_reviewing", "Depósito en revisión"),
    ("deposit_bank_linked", "Movimiento bancario vinculado"),
    ("deposit_verified", "Movimiento bancario verificado"),
    ("deposit_rejected", "Depósito rechazado"),
    ("deposit_applied", "Pago conciliado y aplicado"),
    ("ticket_created", "Solicitud registrada"),
    ("ticket_assigned", "Responsable de solicitud actualizado"),
    ("ticket_state", "Estado de solicitud actualizado"),
    ("ticket_public_reply", "Respuesta pública a solicitud"),
    ("notice_published", "Aviso publicado"),
    ("installment_schedule", "Calendario de financiamiento generado"),
    ("installment_reminder", "Recordatorio de cuota"),
    ("installment_paid", "Cuota pagada según Contabilidad"),
    ("installment_invoice_posted", "Factura de cuota publicada"),
]

CATEGORY_SETTING = {
    "billing": "billing_enabled", "deposits": "deposits_enabled",
    "helpdesk": "helpdesk_enabled", "notices": "notices_enabled",
    "financing": "financing_enabled",
}

OPTIONAL_PREFERENCES = {
    "invoice_reminder": "kabay_notify_invoice_reminders",
    "ticket_assigned": "kabay_notify_ticket_updates",
    "ticket_state": "kabay_notify_ticket_updates",
    "ticket_public_reply": "kabay_notify_ticket_updates",
    "notice_published": "kabay_notify_notices",
    "installment_reminder": "kabay_notify_financing_reminders",
}


class KabayNotification(models.Model):
    _name = "kabay.notification"
    _description = "Evento de comunicación Kabay"
    _order = "create_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(required=True, index=True)
    event_type = fields.Selection(EVENTS, required=True, index=True)
    category = fields.Selection([
        ("billing", "Facturación"), ("deposits", "Depósitos"),
        ("helpdesk", "Solicitudes"), ("notices", "Avisos"),
        ("financing", "Financiamiento"),
    ], required=True, index=True)
    source_model = fields.Char(required=True, index=True)
    source_res_id = fields.Integer(required=True, index=True)
    event_identifier = fields.Char(required=True, index=True)
    event_data = fields.Json(default=dict, copy=False)
    company_id = fields.Many2one("res.company", required=True, index=True, ondelete="restrict")
    recipient_id = fields.Many2one("res.partner", required=True, index=True, ondelete="restrict")
    event_date = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    state = fields.Selection([
        ("pending", "Pendiente"), ("queued", "En cola Odoo"),
        ("sent", "Enviado"), ("failed", "Fallido"),
        ("skipped", "Omitido"), ("cancelled", "Cancelado"),
    ], required=True, default="pending", index=True)
    attempt_count = fields.Integer(default=0, readonly=True)
    last_error = fields.Text(readonly=True)
    next_retry_at = fields.Datetime(index=True)
    sent_at = fields.Datetime(readonly=True)
    mail_ids = fields.One2many("mail.mail", "kabay_notification_id", string="Correos Odoo", readonly=True)
    source_label = fields.Char(compute="_compute_source_label")
    email_subject = fields.Char(compute="_compute_email_content")
    email_body_html = fields.Html(compute="_compute_email_content", sanitize=True)

    _event_unique = models.Constraint(
        "unique(source_model, source_res_id, event_type, recipient_id, company_id, event_identifier)",
        "Este evento ya fue registrado para el destinatario.",
    )

    @api.depends("source_model", "source_res_id")
    def _compute_source_label(self):
        for notification in self:
            try:
                source = self.env[notification.source_model].browse(notification.source_res_id).exists()
                notification.source_label = source.display_name if source else _("Registro eliminado")
            except (KeyError, TypeError):
                notification.source_label = _("Origen no disponible")

    @api.depends("event_type", "event_data", "recipient_id")
    def _compute_email_content(self):
        for notification in self:
            data = notification.event_data or {}
            title = " ".join(str(data.get("title") or notification.name).split())[:180]
            notification.email_subject = _("Kabay Group: %s") % title
            rows = []
            for label, key in (
                (_("Condominio"), "condominium"), (_("Apartamento"), "apartment"),
                (_("Factura"), "invoice"), (_("Fecha de emisión"), "invoice_date"),
                (_("Vencimiento"), "due_date"), (_("Concepto"), "concept"),
                (_("Importe"), "amount"), (_("Estado"), "status"),
                (_("Contrato"), "contract"), (_("Cuota"), "installment"),
                (_("Categoría"), "category"), (_("Prioridad"), "priority"),
                (_("Fecha de creación"), "create_date"), (_("Responsable"), "assignee"),
            ):
                value = data.get(key)
                if value not in (None, False, ""):
                    rows.append("<li><b>%s:</b> %s</li>" % (escape(str(label)), escape(str(value))))
            reply = data.get("public_reply")
            if notification.event_type == "ticket_public_reply":
                try:
                    message_id = int(notification.event_identifier.rsplit(":", 1)[-1])
                    message = self.env["mail.message"].browse(message_id).exists()
                    if message and message.subtype_id and not message.subtype_id.internal and message.subtype_id != self.env.ref("mail.mt_note"):
                        reply = html_sanitize(message.body or "")
                except (ValueError, KeyError):
                    reply = False
            if reply:
                rows.append("<li><b>%s:</b> %s</li>" % (escape(str(_("Respuesta pública"))), reply))
            note = data.get("message")
            if notification.event_type == "deposit_rejected":
                try:
                    declaration = self.env["kabay.deposit.declaration"].browse(notification.source_res_id).exists()
                    note = declaration.rejection_reason if declaration else note
                except KeyError:
                    pass
            if note:
                rows.append("<p>%s</p>" % escape(str(note)))
            warning = data.get("warning")
            if warning:
                rows.append("<p><b>%s</b></p>" % escape(str(warning)))
            url = data.get("portal_url")
            if notification.event_type == "notice_published":
                try:
                    notice = self.env["kabay.notice"].browse(notification.source_res_id).exists()
                    if notice and notice.state in ("published", "finished"):
                        rows.append("<li>%s</li>" % html_sanitize(notice.content or ""))
                except KeyError:
                    pass
            link = "<p><a href=\"%s\">%s</a></p>" % (escape(url, quote=True), escape(str(_("Abrir en el portal privado")))) if url else ""
            notification.email_body_html = Markup(
                "<div><p>%s</p><ul>%s</ul>%s</div>"
                % (escape(str(data.get("intro") or title)), "".join(rows), link)
            )

    @api.model
    def _capture(self, *, source, event_type, category, recipient, company, event_identifier, data=None, event_date=None):
        """Create an immutable, deduplicated outbox event with a fixed recipient."""
        if not source or not source.exists() or len(source) != 1:
            return self.browse()
        if not recipient or not recipient.exists() or len(recipient) != 1 or not company:
            return self.browse()
        if recipient.company_id and recipient.company_id != company:
            return self.browse()
        if event_type not in dict(EVENTS) or category not in CATEGORY_SETTING:
            return self.browse()
        setting = self.env["kabay.notification.settings"].sudo()._for_company(company)
        category_enabled = bool(setting[CATEGORY_SETTING[category]])
        preference = OPTIONAL_PREFERENCES.get(event_type)
        preference_enabled = not preference or bool(recipient[preference])
        eligible_email = bool(recipient.active and recipient.email and not recipient.is_blacklisted)
        state = "pending" if category_enabled and preference_enabled and eligible_email else "skipped"
        reason = False
        if not category_enabled:
            reason = _("Categoría desactivada en configuración.")
        elif not preference_enabled:
            reason = _("El residente desactivó esta comunicación opcional.")
        elif not eligible_email:
            reason = _("El contacto no tiene correo autorizado o está en la lista de exclusión de Odoo.")
        vals = {
            "name": dict(EVENTS)[event_type], "event_type": event_type, "category": category,
            "source_model": source._name, "source_res_id": source.id,
            "event_identifier": str(event_identifier), "event_data": data or {},
            "company_id": company.id, "recipient_id": recipient.id,
            "event_date": event_date or fields.Datetime.now(), "state": state, "last_error": reason,
        }
        domain = [
            ("source_model", "=", source._name), ("source_res_id", "=", source.id),
            ("event_type", "=", event_type), ("recipient_id", "=", recipient.id),
            ("company_id", "=", company.id), ("event_identifier", "=", str(event_identifier)),
        ]
        existing = self.sudo().search(domain, limit=1)
        if existing:
            return existing
        try:
            with self.env.cr.savepoint():
                return self.sudo().create(vals)
        except psycopg2.IntegrityError:
            return self.sudo().search(domain, limit=1)
        except Exception as error:
            _logger.warning("Kabay notification capture failed (%s)", type(error).__name__)
            return self.browse()

    def action_retry(self):
        is_manager = self.env.user.has_group("kabay_base.group_kabay_manager")
        is_finance = self.env.user.has_group("kabay_base.group_kabay_finance")
        if not is_manager and not is_finance:
            raise AccessError(_("Solo Administración o Finanzas puede reintentar comunicaciones."))
        for event in self:
            if is_finance and not is_manager and event.category not in ("billing", "deposits", "financing"):
                raise AccessError(_("Finanzas solo puede reintentar notificaciones contables."))
            setting = self.env["kabay.notification.settings"].sudo()._for_company(event.company_id)
            if event.state != "failed" or event.attempt_count >= setting.max_attempts:
                raise UserError(_("Solo se pueden reintentar eventos fallidos con intentos disponibles."))
            event.sudo().write({"state": "pending", "next_retry_at": fields.Datetime.now(), "last_error": False})
        return True

    def write(self, vals):
        if not self.env.is_system():
            raise AccessError(_("El registro de comunicaciones es de solo lectura."))
        if set(vals) - {"state", "attempt_count", "last_error", "next_retry_at", "sent_at"}:
            raise AccessError(_("Los datos de auditoría del evento no se pueden sustituir."))
        return super().write(vals)

    @api.model
    def _cron_generate_invoice_reminders(self, settings):
        Move = self.env["account.move"]
        for setting in settings:
            company = setting.company_id
            tz = company.partner_id.tz or self.env.user.tz or "UTC"
            today = fields.Date.context_today(self.with_context(tz=tz))
            offsets = {
                setting.reminder_days_before_first: -setting.reminder_days_before_first,
                setting.reminder_days_before_second: -setting.reminder_days_before_second,
                setting.reminder_days_before_due: 0,
                -setting.reminder_days_after: setting.reminder_days_after,
            }
            for delta, days_value in offsets.items():
                due = today + timedelta(days=delta)
                domain = [
                    ("company_id", "=", company.id), ("move_type", "=", "out_invoice"),
                    ("state", "=", "posted"), ("amount_residual", ">", 0),
                    ("invoice_date_due", "=", due), ("kabay_responsible_id", "!=", False),
                    ("kabay_financing_installment_id", "=", False),
                ]
                moves = Move.search(domain, limit=1000)
                for move in moves:
                    if not self._kabay_is_invoice_reminder_eligible(move):
                        continue
                    responsible = move.kabay_responsible_id
                    self._capture(
                        source=move, event_type="invoice_reminder", category="billing",
                        recipient=responsible, company=company,
                        event_identifier="due:%s:offset:%s" % (fields.Date.to_string(due), days_value),
                        data=self.env["account.move"]._kabay_notification_data(move, "reminder", days_value),
                    )

    @api.model
    def _kabay_is_invoice_reminder_eligible(self, move):
        return bool(
            move and move.state == "posted" and move.move_type == "out_invoice"
            and move.amount_residual > 0 and move.invoice_date_due
            and move.kabay_responsible_id and not move.kabay_financing_installment_id
        )

    @api.model
    def _cron_generate_installment_reminders(self, settings):
        Installment = self.env["kabay.financing.installment"]
        for setting in settings:
            company = setting.company_id
            tz = company.partner_id.tz or self.env.user.tz or "UTC"
            today = fields.Date.context_today(self.with_context(tz=tz))
            offsets = {
                setting.reminder_days_before_first: -setting.reminder_days_before_first,
                setting.reminder_days_before_second: -setting.reminder_days_before_second,
                setting.reminder_days_before_due: 0,
                -setting.reminder_days_after: setting.reminder_days_after,
            }
            for delta, days_value in offsets.items():
                due = today + timedelta(days=delta)
                lines = Installment.search([
                    ("company_id", "=", company.id), ("due_date", "=", due),
                    ("state", "in", ["pending", "partial", "overdue"]),
                    ("invoice_id.state", "=", "posted"), ("invoice_id.amount_residual", ">", 0),
                ], limit=1000)
                for line in lines:
                    self.env["kabay.financing.installment"]._kabay_notify_installment(
                        line, "installment_reminder", "due:%s:offset:%s" % (fields.Date.to_string(due), days_value), days_value,
                    )

    @api.model
    def _cron_process_notifications(self):
        settings = self.env["kabay.notification.settings"].sudo().search([("active", "=", True)])
        if not settings:
            return
        self._cron_generate_invoice_reminders(settings.filtered("billing_enabled"))
        self._cron_generate_installment_reminders(settings.filtered("financing_enabled"))
        now = fields.Datetime.now()
        self.env.cr.execute(
            "SELECT id FROM kabay_notification WHERE state IN ('pending','failed') "
            "AND (next_retry_at IS NULL OR next_retry_at <= %s) "
            "ORDER BY event_date, id LIMIT 100 FOR UPDATE SKIP LOCKED",
            [now],
        )
        for (event_id,) in self.env.cr.fetchall():
            event = self.browse(event_id).exists()
            if event:
                event._process_one()

    def _process_one(self):
        self.ensure_one()
        setting = self.env["kabay.notification.settings"].sudo()._for_company(self.company_id)
        preference = OPTIONAL_PREFERENCES.get(self.event_type)
        recipient = self.recipient_id
        if not setting[CATEGORY_SETTING[self.category]]:
            self.sudo().write({"state": "skipped", "last_error": _("Categoría desactivada antes del envío.")})
            return False
        if not recipient.active or not recipient.email or recipient.is_blacklisted:
            self.sudo().write({"state": "skipped", "last_error": _("El contacto ya no tiene correo autorizado en Odoo.")})
            return False
        if preference and not recipient[preference]:
            self.sudo().write({"state": "skipped", "last_error": _("El residente desactivó esta comunicación opcional antes del envío.")})
            return False
        if not setting.active:
            self.sudo().write({"last_error": _("La configuración de comunicaciones está pausada para esta compañía.")})
            return False
        if not setting.delivery_enabled:
            self.sudo().write({"last_error": _("Envío desactivado para esta compañía.")})
            return False
        Server = self.env["ir.mail_server"].sudo()
        server_domain = [("active", "=", True)]
        if "company_id" in Server._fields:
            server_domain += ["|", ("company_id", "=", False), ("company_id", "=", self.company_id.id)]
        if not Server.search_count(server_domain):
            self.sudo().write({"last_error": _("No hay un servidor de correo saliente activo en Odoo.")})
            return False
        if self.attempt_count >= setting.max_attempts:
            self.sudo().write({"state": "failed", "last_error": _("Se alcanzó el límite configurado de intentos.")})
            return False
        template = setting._template_for(self.category)
        if not template:
            template = self.env.ref("kabay_notifications.mail_template_kabay_%s" % self.category, raise_if_not_found=False)
        if not template or template.model != self._name:
            self.sudo().write({"state": "failed", "attempt_count": self.attempt_count + 1,
                               "last_error": _("No existe una plantilla válida para esta categoría.")})
            return False
        try:
            with self.env.cr.savepoint():
                mail_id = template.with_company(self.company_id).send_mail(
                    self.id, force_send=False, raise_exception=True,
                    email_values={
                        "email_to": self.recipient_id.email,
                        "recipient_ids": [(6, 0, [self.recipient_id.id])],
                        "kabay_notification_id": self.id,
                        "auto_delete": True,
                    },
                )
                if not mail_id:
                    raise UserError(_("Odoo no generó un correo en su cola."))
                mail = self.env["mail.mail"].browse(mail_id)
                self.sudo().write({
                    "state": "queued", "attempt_count": self.attempt_count + 1,
                    "last_error": False, "next_retry_at": False,
                })
            return True
        except Exception as error:
            _logger.warning("Could not queue Kabay notification (%s)", type(error).__name__)
            delay = timedelta(minutes=setting.retry_minutes * max(self.attempt_count + 1, 1))
            self.sudo().write({
                "state": "failed", "attempt_count": self.attempt_count + 1,
                "last_error": _("Odoo no pudo poner el mensaje en cola. Revise el registro técnico protegido."),
                "next_retry_at": fields.Datetime.now() + delay,
            })
            return False
