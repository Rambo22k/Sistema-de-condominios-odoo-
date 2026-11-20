import logging

from odoo import fields, http, _
from odoo.exceptions import AccessError
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal
from werkzeug.exceptions import NotFound


_logger = logging.getLogger(__name__)


class KabayResidentPortal(CustomerPortal):
    @http.route()
    def home(self, **kw):
        user = request.env.user
        if (user.has_group("kabay_deposits.group_kabay_deposit_resident")
                and not user.has_group("base.group_user")):
            return request.redirect("/my/kabay")
        return super().home(**kw)

    def _resident(self):
        user = request.env.user
        if (not user.has_group("kabay_deposits.group_kabay_deposit_resident")
                or user.has_group("base.group_user")):
            raise NotFound()
        return user.partner_id

    def _relations(self):
        partner = self._resident()
        today = fields.Date.context_today(request.env.user)
        return request.env["kabay.apartment.relation"].search([
            ("partner_id", "=", partner.id), ("state", "=", "confirmed"),
            ("active", "=", True), ("date_start", "<=", today),
            "|", ("date_end", "=", False), ("date_end", ">=", today),
        ], order="apartment_id, role")

    def _units(self):
        return self._relations().mapped("apartment_id")

    def _unit_or_404(self, apartment_id):
        apartment = self._units().filtered(lambda unit: unit.id == apartment_id)
        if len(apartment) != 1:
            raise NotFound()
        return apartment

    def _layout(self, page_name, **values):
        values.update({
            "page_name": page_name,
            "kabay_resident": self._resident(),
            "no_breadcrumbs": True,
            "no_footer": True,
        })
        return values

    @http.route("/my/kabay", type="http", auth="user", website=True, methods=["GET"])
    def kabay_home(self, **kwargs):
        partner = self._resident()
        relations = self._relations()
        units = relations.mapped("apartment_id")
        invoices = self._invoices(units)
        notices = request.env["kabay.notice"].search([
            ("state", "=", "published"), ("publish_datetime", "<=", fields.Datetime.now()),
        ], order="publish_datetime desc, id desc", limit=30)
        visible_notices = request.env["kabay.notice"]
        for notice in notices:
            try:
                notice._portal_check_access()
                visible_notices |= notice
            except AccessError:
                continue
        tickets = request.env["helpdesk.ticket"].search([
            ("partner_id", "=", partner.id), ("kabay_apartment_id", "in", units.ids),
        ], order="create_date desc", limit=5)
        deposits = request.env["kabay.deposit.declaration"].search([
            ("declarant_partner_id", "=", partner.id), ("apartment_id", "in", units.ids),
        ], order="create_date desc", limit=5)
        return request.render("kabay_portal.portal_dashboard", self._layout(
            "kabay_home", relations=relations, units=units, invoices=invoices,
            notices=visible_notices[:5], tickets=tickets, deposits=deposits,
            open_balance=sum(move["residual"] for move in invoices),
            currency=(units[:1].company_id.currency_id if units else request.env.company.currency_id),
            role_labels=dict(request.env["kabay.apartment.relation"]._fields["role"].selection),
            # The related selection on helpdesk.ticket is callable because its
            # options are supplied by the Helpdesk stage configuration.
            ticket_state_labels=dict(request.env["helpdesk.ticket"]._fields["kabay_state"]._description_selection(request.env)),
        ))

    @http.route("/my/kabay/units", type="http", auth="user", website=True, methods=["GET"])
    def kabay_units(self, **kwargs):
        relations = self._relations()
        return request.render("kabay_portal.portal_units", self._layout(
            "kabay_units", relations=relations,
            role_labels=dict(request.env["kabay.apartment.relation"]._fields["role"].selection),
        ))

    @http.route("/my/kabay/units/<int:apartment_id>", type="http", auth="user", website=True, methods=["GET"])
    def kabay_unit_detail(self, apartment_id, **kwargs):
        apartment = self._unit_or_404(apartment_id)
        relation = self._relations().filtered(lambda rel: rel.apartment_id == apartment)[:1]
        # Only the resident's current relation unlocks these photos. Binary URLs are
        # served by this controller so the base64 field is never exposed in QWeb.
        return request.render("kabay_portal.portal_unit_detail", self._layout(
            "kabay_units", apartment=apartment, relation=relation,
            photos=apartment.photo_ids,
            role_label=dict(relation._fields["role"].selection).get(relation.role),
        ))

    @http.route("/my/kabay/units/<int:apartment_id>/photo/<int:photo_id>", type="http", auth="user", website=True, methods=["GET"])
    def kabay_unit_photo(self, apartment_id, photo_id, **kwargs):
        apartment = self._unit_or_404(apartment_id)
        photo = apartment.photo_ids.filtered(lambda item: item.id == photo_id)
        if not photo:
            raise NotFound()
        stream = request.env["ir.binary"]._get_stream_from(photo, "image", filename=photo.name)
        return stream.get_response(as_attachment=False)

    @http.route("/my/kabay/invoices", type="http", auth="user", website=True, methods=["GET"])
    def kabay_invoices(self, apartment_id=None, state="open", **kwargs):
        self._resident()
        units = self._units()
        if apartment_id:
            units = self._unit_or_404(int(apartment_id))
        invoices = self._invoices(units)
        if state == "open":
            invoices = [move for move in invoices if move["residual"] > 0]
        return request.render("kabay_portal.portal_invoices", self._layout(
            "kabay_invoices", invoices=invoices, units=self._units(), selected=apartment_id or "",
            state=state, currency=(units[:1].company_id.currency_id if units else request.env.company.currency_id),
        ))

    def _invoices(self, units):
        if not units:
            return []
        # Odoo's Portal read ACL is restricted by its native account.move record
        # rule. Use the validated Kabay disclosure method as well so only eligible
        # invoices for the resident's current apartment are returned here.
        helper = request.env["kabay.deposit.declaration"]
        rows = []
        for unit in units:
            rows.extend({**option, "apartment": unit, "state_label": "Pendiente"}
                        for option in helper.portal_invoice_options(unit.id))
        return rows

    @http.route("/my/kabay/financing", type="http", auth="user", website=True, methods=["GET"])
    def kabay_financing(self, **kwargs):
        partner = self._resident()
        units = self._units()
        contracts = request.env["kabay.financing.contract"].search([
            ("buyer_id", "=", partner.id), ("apartment_id", "in", units.ids),
            ("state", "in", ["active", "suspended"]), ("company_id", "in", request.env.companies.ids),
        ], order="start_date desc") if units else request.env["kabay.financing.contract"]
        return request.render("kabay_portal.portal_financing", self._layout(
            "kabay_financing", contracts=contracts,
            installment_state_labels=dict(request.env["kabay.financing.installment"]._fields["state"].selection),
            payment_timing_labels=dict(request.env["kabay.financing.installment"]._fields["payment_timing"].selection),
        ))

    @http.route("/my/kabay/profile", type="http", auth="user", website=True, methods=["GET", "POST"])
    def kabay_profile(self, **post):
        partner = self._resident()
        error = None
        saved = False
        if request.httprequest.method == "POST":
            allowed = {key: (post.get(key) or "").strip() for key in ("name", "email", "phone")}
            try:
                partner.write(allowed)
                saved = True
            except Exception as exc:
                # Validation/SQL exceptions may contain internal details or the
                # submitted values. Keep the response generic and logs non-PII.
                _logger.warning("Kabay portal profile update failed (%s)", type(exc).__name__)
                error = _("No se pudieron guardar los datos del perfil. Revise los campos e inténtelo nuevamente.")
        return request.render("kabay_portal.portal_profile", self._layout(
            "kabay_profile", partner=partner, error=error, saved=saved,
        ))

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        user = request.env.user
        if user.has_group("base.group_portal") and not user.has_group("base.group_user"):
            values["kabay_home_url"] = "/my/kabay"
        return values
