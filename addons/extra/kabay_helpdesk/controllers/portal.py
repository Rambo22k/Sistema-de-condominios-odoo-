import base64

from odoo import _, fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from werkzeug.exceptions import NotFound

from odoo.addons.kabay_helpdesk.models.helpdesk import PORTAL_MAX_FILE_SIZE


PORTAL_MAX_FILES_PER_REQUEST = 5
PORTAL_MAX_TOTAL_FILE_SIZE = 20 * 1024 * 1024


def _read_portal_uploads(file_storages, ticket_id, *, max_file_size=PORTAL_MAX_FILE_SIZE,
                         max_files=PORTAL_MAX_FILES_PER_REQUEST,
                         max_total_size=PORTAL_MAX_TOTAL_FILE_SIZE):
    """Read bounded resident uploads; never buffer an unbounded file in memory."""
    uploads = [item for item in file_storages if item and item.filename]
    if len(uploads) > max_files:
        raise ValidationError(_("Puede adjuntar como máximo %s archivos por envío.") % max_files)
    total_size = 0
    values = []
    for uploaded in uploads:
        content = uploaded.stream.read(max_file_size + 1)
        if len(content) > max_file_size:
            raise ValidationError(_("Cada archivo debe tener un máximo de 10 MB."))
        total_size += len(content)
        if total_size > max_total_size:
            raise ValidationError(_("El tamaño total de los archivos supera el límite permitido."))
        if content:
            values.append({
                "ticket_id": ticket_id,
                "name": uploaded.filename,
                "datas": base64.b64encode(content),
            })
    return values


KABAY_TICKET_STATES = [
    ("new", "Nuevo"), ("review", "En revisión"), ("assigned", "Asignado"),
    ("in_progress", "En progreso"), ("waiting_resident", "En espera del residente"),
    ("resolved", "Resuelto"), ("closed", "Cerrado"), ("cancelled", "Cancelado"),
]


class KabayHelpdeskPortal(CustomerPortal):
    _items_per_page = 10

    def _require_resident_portal(self):
        user = request.env.user
        if not user.has_group("base.group_portal") or user.has_group("base.group_user"):
            raise NotFound()

    @http.route("/my/kabay/tickets", type="http", auth="user", website=True, methods=["GET"])
    def kabay_ticket_list(self, page=1, state="all", **kwargs):
        self._require_resident_portal()
        Ticket = request.env["helpdesk.ticket"]
        domain = [("partner_id", "=", request.env.user.partner_id.id), ("kabay_apartment_id", "!=", False)]
        if state in dict(KABAY_TICKET_STATES):
            domain.append(("kabay_state", "=", state))
        total = Ticket.search_count(domain)
        pager = portal_pager(url="/my/kabay/tickets", total=total, page=page, step=self._items_per_page, url_args={"state": state})
        tickets = Ticket.search(domain, order="create_date desc, id desc", limit=self._items_per_page, offset=pager["offset"])
        return request.render("kabay_helpdesk.portal_ticket_list", {"tickets": tickets, "pager": pager, "state": state, "state_options": KABAY_TICKET_STATES})

    @http.route("/my/kabay/tickets/new", type="http", auth="user", website=True, methods=["GET", "POST"])
    def kabay_ticket_new(self, **post):
        self._require_resident_portal()
        partner = request.env.user.partner_id
        relations = request.env["helpdesk.ticket"]._kabay_current_relations(partner)
        categories = request.env["kabay.helpdesk.category"].search([("active", "=", True), "|", ("company_id", "=", False), ("company_id", "in", relations.mapped("company_id").ids)])
        error = None
        if request.httprequest.method == "POST":
            try:
                with request.env.cr.savepoint():
                    ticket = request.env["helpdesk.ticket"].create({
                        "name": post.get("name"), "description": post.get("description"),
                        "kabay_apartment_id": int(post.get("apartment_id") or 0),
                        "kabay_category_id": int(post.get("category_id") or 0),
                        "priority": post.get("priority", "1"),
                    })
                    attachment_values = _read_portal_uploads(
                        request.httprequest.files.getlist("files"), ticket.id,
                    )
                    if attachment_values:
                        request.env["kabay.helpdesk.attachment"].create(attachment_values)
                return request.redirect("/my/kabay/tickets/%s" % ticket.id)
            except (AccessError, UserError, ValidationError, ValueError) as exc:
                error = str(exc)
        return request.render("kabay_helpdesk.portal_ticket_new", {"relations": relations, "categories": categories, "error": error, "post": post})

    @http.route("/my/kabay/tickets/<int:ticket_id>", type="http", auth="user", website=True, methods=["GET", "POST"])
    def kabay_ticket_detail(self, ticket_id, **post):
        self._require_resident_portal()
        ticket = request.env["helpdesk.ticket"].browse(ticket_id).exists()
        if not ticket:
            raise NotFound()
        try:
            ticket._kabay_portal_check_access()
            if request.httprequest.method == "POST":
                with request.env.cr.savepoint():
                    if post.get("action") == "reopen":
                        ticket.action_kabay_portal_reopen()
                    else:
                        body = (post.get("body") or "").strip()
                        if not body:
                            raise ValidationError("Escriba una respuesta antes de enviarla.")
                        ticket.message_post(body=body, message_type="comment", subtype_xmlid="mail.mt_comment")
                    attachment_values = _read_portal_uploads(
                        request.httprequest.files.getlist("files"), ticket.id,
                    )
                    if attachment_values:
                        request.env["kabay.helpdesk.attachment"].create(attachment_values)
                return request.redirect("/my/kabay/tickets/%s" % ticket.id)
        except (AccessError, UserError, ValidationError) as exc:
            if isinstance(exc, AccessError):
                raise NotFound()
            return request.render("kabay_helpdesk.portal_ticket_detail", {"ticket": ticket, "messages": ticket._kabay_public_messages(), "error": str(exc)})
        messages = ticket._kabay_public_messages()
        return request.render("kabay_helpdesk.portal_ticket_detail", {"ticket": ticket, "messages": messages, "error": None})

    @http.route("/my/kabay/tickets/file/<int:attachment_id>", type="http", auth="user", website=True, methods=["GET"])
    def kabay_ticket_file(self, attachment_id, **kwargs):
        self._require_resident_portal()
        attachment = request.env["kabay.helpdesk.attachment"].browse(attachment_id).exists()
        if not attachment:
            raise NotFound()
        try:
            attachment.ticket_id._kabay_portal_check_access()
            attachment.check_access("read")
        except AccessError:
            raise NotFound()
        stream = request.env["ir.binary"]._get_stream_from(
            attachment, "datas", filename=attachment.name, mimetype=attachment.mimetype,
        )
        return stream.get_response(as_attachment=True)

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if "kabay_ticket_count" in counters and request.env["helpdesk.ticket"].has_access("read"):
            values["kabay_ticket_count"] = request.env["helpdesk.ticket"].search_count([
                ("partner_id", "=", request.env.user.partner_id.id), ("kabay_apartment_id", "!=", False),
            ])
        return values
