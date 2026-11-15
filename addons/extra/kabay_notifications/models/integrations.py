from html import escape
import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.tools import html_sanitize


_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    @api.model
    def _kabay_notification_data(self, move, kind, days_value=None):
        move.ensure_one()
        condo = move.kabay_condominium_id or move.kabay_financing_apartment_id.condominium_id
        apartment = move.kabay_apartment_id or move.kabay_financing_apartment_id
        lines = [line.name for line in move.invoice_line_ids if line.name]
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
        is_financing = bool(move.kabay_financing_installment_id)
        portal_path = "/my/kabay/financing" if is_financing else "/my/kabay/invoices"
        title = move.name or _("Factura")
        intro = _("La factura fue publicada en Contabilidad.")
        if kind == "credit_note":
            title = _("Nota de crédito %s") % (move.name or "")
            intro = _("Se publicó una nota de crédito. No es una factura ordinaria.")
        elif kind == "reminder":
            title = _("Recordatorio de vencimiento: %s") % (move.name or "")
            if days_value < 0:
                intro = _("Tu factura vence en %s día(s).") % abs(days_value)
            elif days_value == 0:
                intro = _("Tu factura vence hoy.")
            else:
                intro = _("Tu factura está vencida desde hace %s día(s).") % days_value
        elif is_financing:
            title = _("Factura de cuota %s") % move.kabay_financing_installment_id.number
            intro = _("La factura de esta cuota de financiamiento fue publicada en Contabilidad.")
        return {
            "title": title, "intro": intro,
            "condominium": condo.name if condo else "",
            "apartment": apartment.code or apartment.name if apartment else "",
            "invoice": move.name or "",
            "invoice_date": fields.Date.to_string(move.invoice_date) if move.invoice_date else "",
            "due_date": fields.Date.to_string(move.invoice_date_due) if move.invoice_date_due else "",
            "concept": "; ".join(lines)[:500],
            "amount": "%s %s" % (move.currency_id.round(move.amount_total), move.currency_id.name),
            "status": dict(move._fields["payment_state"].selection).get(move.payment_state, move.payment_state),
            "contract": move.kabay_financing_contract_id.name if move.kabay_financing_contract_id else "",
            "installment": str(move.kabay_financing_installment_id.number) if move.kabay_financing_installment_id else "",
            "message": _("Saldo pendiente: %s %s") % (move.currency_id.round(move.amount_residual), move.currency_id.name)
                if kind == "reminder" else "",
            "portal_url": base_url + portal_path if base_url else "",
        }

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        for move in posted.filtered(lambda item: item.state == "posted" and item.move_type in ("out_invoice", "out_refund")):
            installment = move.kabay_financing_installment_id
            recipient = move.kabay_responsible_id or (installment.contract_id.buyer_id if installment else move.partner_id)
            if not (move.kabay_responsible_id or installment):
                continue
            if recipient != move.partner_id:
                _logger.warning("Skip Kabay email event: invoice %s partner does not match its stored responsible", move.id)
                continue
            if move.move_type == "out_refund":
                event_type = "credit_note_posted"
                kind = "credit_note"
                category = "billing"
            elif installment:
                event_type = "installment_invoice_posted"
                kind = "invoice"
                category = "financing"
            else:
                event_type = "invoice_posted"
                kind = "invoice"
                category = "billing"
            self.env["kabay.notification"]._capture(
                source=move, event_type=event_type, category=category,
                recipient=recipient, company=move.company_id,
                event_identifier="posted:%s" % move.name,
                data=self._kabay_notification_data(move, kind),
            )
        return posted

    def write(self, vals):
        previous = {move.id: move.payment_state for move in self} if "payment_state" in vals else {}
        result = super().write(vals)
        if "payment_state" in vals:
            for move in self.filtered(lambda item: item.state == "posted" and item.payment_state == "paid" and previous.get(item.id) != "paid"):
                line = move.kabay_financing_installment_id
                if not line or move.partner_id != line.contract_id.buyer_id:
                    continue
                self.env["kabay.financing.installment"]._kabay_notify_installment(
                    line, "installment_paid", "account-paid:%s" % move.id,
                    data={"title": _("Cuota pagada"), "intro": _("Contabilidad de Odoo confirma que la factura de esta cuota está pagada."),
                          "status": _("Pagada"), "portal_url": self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/") + "/my/kabay/financing"},
                )
        return result


class KabayDepositDeclaration(models.Model):
    _inherit = "kabay.deposit.declaration"

    def _kabay_notify_deposit(self, event_type, message, event_identifier):
        Notification = self.env["kabay.notification"]
        for declaration in self:
            Notification._capture(
                source=declaration, event_type=event_type, category="deposits",
                recipient=declaration.declarant_partner_id, company=declaration.company_id,
                event_identifier=event_identifier,
                data={
                    "title": declaration.name,
                    "intro": message,
                    "apartment": declaration.apartment_id.code or declaration.apartment_id.name,
                    "amount": "%s %s" % (declaration.currency_id.round(declaration.amount), declaration.currency_id.name),
                    "status": dict(declaration._fields["state"].selection).get(declaration.state, declaration.state),
                    "warning": _("La verificación del movimiento bancario no confirma un pago.") if event_type in ("deposit_bank_linked", "deposit_verified") else "",
                    "portal_url": self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/") + "/my/kabay/deposits",
                },
            )

    def write(self, vals):
        previous = {declaration.id: declaration.statement_line_id.id for declaration in self} if "statement_line_id" in vals else {}
        result = super().write(vals)
        if "statement_line_id" in vals:
            for declaration in self.filtered(lambda item: item.statement_line_id and previous.get(item.id) != item.statement_line_id.id):
                declaration._kabay_notify_deposit(
                    "deposit_bank_linked", _("Se vinculó un movimiento bancario para revisión. Aún no es un pago confirmado."),
                    "bank-line:%s" % declaration.statement_line_id.id,
                )
        return result

    def action_submit(self):
        result = super().action_submit()
        self._kabay_notify_deposit("deposit_submitted", _("Tu declaración de depósito fue recibida para revisión."), "submitted:%s" % fields.Datetime.now())
        return result

    def action_start_review(self):
        result = super().action_start_review()
        self._kabay_notify_deposit("deposit_reviewing", _("Finanzas inició la revisión de tu declaración."), "reviewing:%s" % fields.Datetime.now())
        return result

    def action_verify_bank_line(self):
        result = super().action_verify_bank_line()
        self._kabay_notify_deposit("deposit_verified", _("La referencia bancaria fue verificada. El pago todavía no ha sido aplicado ni conciliado."), "verified:%s" % fields.Datetime.now())
        return result

    def action_reject(self, reason):
        result = super().action_reject(reason)
        self._kabay_notify_deposit("deposit_rejected", _("Finanzas rechazó la declaración de depósito."), "rejected:%s" % fields.Datetime.now())
        return result

    def action_apply(self):
        result = super().action_apply()
        for declaration in self.filtered(lambda item: item.state == "applied" and item.statement_line_id.is_reconciled):
            declaration._kabay_notify_deposit("deposit_applied", _("El pago fue aplicado y la conciliación bancaria se completó en Contabilidad."), "applied:%s" % declaration.applied_at)
        return result


class KabayFinancingContract(models.Model):
    _inherit = "kabay.financing.contract"

    def action_confirm(self):
        result = super().action_confirm()
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
        for contract in self.filtered(lambda item: item.state == "active"):
            for line in contract.installment_ids:
                self.env["kabay.notification"]._capture(
                    source=line, event_type="installment_schedule", category="financing",
                    recipient=contract.buyer_id, company=contract.company_id,
                    event_identifier="schedule:%s:%s" % (contract.id, line.number),
                    data={
                        "title": _("Cuota %s programada") % line.number,
                        "intro": _("Se generó el calendario de tu contrato de financiamiento."),
                        "apartment": contract.apartment_id.code or contract.apartment_id.name,
                        "contract": contract.name, "installment": str(line.number),
                        "amount": "%s %s" % (contract.currency_id.round(line.amount_total), contract.currency_id.name),
                        "due_date": fields.Date.to_string(line.due_date),
                        "status": _("Programada"), "portal_url": base_url + "/my/kabay/financing" if base_url else "",
                    },
                )
        return result


class KabayFinancingInstallment(models.Model):
    _inherit = "kabay.financing.installment"

    def _kabay_notify_installment(self, line, event_type, event_identifier, days_value=None, data=None):
        line.ensure_one()
        contract = line.contract_id
        if data is None:
            base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
            if days_value < 0:
                intro = _("Tu cuota vence en %s día(s).") % abs(days_value)
            elif days_value == 0:
                intro = _("Tu cuota vence hoy.")
            else:
                intro = _("Tu cuota está vencida desde hace %s día(s).") % days_value
            data = {
                "title": _("Recordatorio cuota %s") % line.number, "intro": intro,
                "apartment": contract.apartment_id.code or contract.apartment_id.name,
                "contract": contract.name, "installment": str(line.number),
                "amount": "%s %s" % (contract.currency_id.round(line.balance), contract.currency_id.name),
                "due_date": fields.Date.to_string(line.due_date),
                "status": dict(line._fields["state"].selection).get(line.state, line.state),
                "portal_url": base_url + "/my/kabay/financing" if base_url else "",
            }
        self.env["kabay.notification"]._capture(
            source=line, event_type=event_type, category="financing",
            recipient=contract.buyer_id, company=contract.company_id,
            event_identifier=event_identifier, data=data,
        )


class KabayNotice(models.Model):
    _inherit = "kabay.notice"

    def _kabay_notify_published(self):
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
        for notice in self.filtered(lambda item: item.state == "published" and item.published_at):
            partners = notice.recipient_ids.mapped("partner_id")
            for partner in partners:
                self.env["kabay.notification"]._capture(
                    source=notice, event_type="notice_published", category="notices",
                    recipient=partner, company=notice.company_id,
                    event_identifier="published:%s" % notice.published_at,
                    data={
                        "title": notice.name,
                        "intro": notice.summary or _("Se publicó un aviso para tu comunidad."),
                        "portal_url": base_url + "/my/kabay/notices/%s" % notice.id if base_url else "",
                    },
                    event_date=notice.published_at,
                )

    def action_publish(self):
        result = super().action_publish()
        self._kabay_notify_published()
        return result

    @api.model
    def _cron_update_publication_states(self):
        due_ids = self.search([("state", "=", "scheduled"), ("publish_datetime", "<=", fields.Datetime.now())]).ids
        result = super()._cron_update_publication_states()
        self.browse(due_ids).exists()._kabay_notify_published()
        return result


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    def _kabay_ticket_data(self, title, status=None, assignee=None):
        self.ensure_one()
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
        state = status if status is not None else self.stage_id.name
        return {
            "title": title, "intro": title,
            "category": self.kabay_category_id.name or "",
            "status": state,
            "priority": dict(self._fields["priority"].selection).get(self.priority, self.priority),
            "create_date": fields.Datetime.to_string(self.create_date) if self.create_date else "",
            "assignee": assignee or "",
            "apartment": self.kabay_apartment_id.code or self.kabay_apartment_id.name,
            "portal_url": base_url + "/my/kabay/tickets/%s" % self.id if base_url else "",
        }

    def _kabay_capture_ticket(self, event_type, identifier, data):
        for ticket in self:
            if ticket.partner_id:
                self.env["kabay.notification"]._capture(
                    source=ticket, event_type=event_type, category="helpdesk",
                    recipient=ticket.partner_id, company=ticket.company_id,
                    event_identifier=identifier, data=data,
                )

    @api.model_create_multi
    def create(self, vals_list):
        tickets = super().create(vals_list)
        for ticket in tickets.filtered(lambda item: item.kabay_apartment_id and item.partner_id):
            ticket._kabay_capture_ticket("ticket_created", "created:%s" % ticket.create_date, ticket._kabay_ticket_data(_("Solicitud registrada")))
        return tickets

    def write(self, vals):
        before = {ticket.id: (ticket.kabay_state, ticket.user_id.id) for ticket in self}
        result = super().write(vals)
        for ticket in self:
            old_state, old_user = before[ticket.id]
            if "user_id" in vals and old_user != ticket.user_id.id and ticket.user_id:
                ticket._kabay_capture_ticket(
                    "ticket_assigned", "assigned:%s:%s" % (ticket.write_date, ticket.user_id.id),
                    ticket._kabay_ticket_data(_("Se actualizó el responsable de tu solicitud."), assignee=ticket.user_id.name),
                )
            if "stage_id" in vals and old_state != ticket.kabay_state:
                ticket._kabay_capture_ticket(
                    "ticket_state", "state:%s:%s:%s" % (ticket.write_date, old_state, ticket.kabay_state),
                    ticket._kabay_ticket_data(_("Cambió el estado de tu solicitud.")),
                )
        return result

    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)
        if not message or message.message_type != "comment" or not message.subtype_id or message.subtype_id.internal:
            return message
        for ticket in self.filtered(lambda item: item.kabay_apartment_id and item.partner_id and item.partner_id != message.author_id):
            ticket._kabay_capture_ticket(
                "ticket_public_reply", "public-reply:%s" % message.id,
                ticket._kabay_ticket_data(_("Hay una respuesta pública en tu solicitud.")),
            )
        return message


class MailMail(models.Model):
    _inherit = "mail.mail"

    kabay_notification_id = fields.Many2one("kabay.notification", index=True, ondelete="set null", copy=False)

    def write(self, vals):
        result = super().write(vals)
        if "state" in vals:
            for mail in self.filtered("kabay_notification_id"):
                event = mail.kabay_notification_id.sudo()
                if mail.state == "sent":
                    event.write({"state": "sent", "sent_at": fields.Datetime.now(), "last_error": False, "next_retry_at": False})
                elif mail.state == "exception":
                    setting = self.env["kabay.notification.settings"].sudo()._for_company(event.company_id)
                    next_try = fields.Datetime.now() + timedelta(minutes=setting.retry_minutes * max(event.attempt_count, 1))
                    event.write({
                        "state": "failed",
                        "last_error": _("Odoo no pudo entregar el mensaje. Revise el registro técnico protegido."),
                        "next_retry_at": next_try,
                    })
                elif mail.state == "cancel":
                    event.write({"state": "cancelled"})
                elif mail.state == "outgoing":
                    event.write({"state": "queued", "last_error": False})
        return result


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _reconcile_post_hook(self, data):
        result = super()._reconcile_post_hook(data)
        paid_invoices = (
            data["not_paid_invoices"].filtered(lambda move: move.payment_state == "paid")
            | data["in_payment_invoices"].filtered(lambda move: move.payment_state == "paid")
        )
        for move in paid_invoices.filtered(lambda item: item.state == "posted" and item.kabay_financing_installment_id):
            line = move.kabay_financing_installment_id
            if move.partner_id == line.contract_id.buyer_id:
                self.env["kabay.financing.installment"]._kabay_notify_installment(
                    line, "installment_paid", "account-paid:%s" % move.id,
                    data={
                        "title": _("Cuota pagada"),
                        "intro": _("Contabilidad de Odoo confirma que la factura de esta cuota está pagada."),
                        "status": _("Pagada"),
                        "portal_url": self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/") + "/my/kabay/financing",
                    },
                )
        return result
