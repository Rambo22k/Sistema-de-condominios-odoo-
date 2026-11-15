import base64
import math

from odoo import _, fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request
from werkzeug.exceptions import NotFound


class KabayDepositPortal(http.Controller):
    def _check_portal_user(self):
        if not request.env.user.has_group("kabay_deposits.group_kabay_deposit_resident"):
            raise NotFound()

    def _form_values(self, apartment_id=None, error=None, form_data=None):
        declaration_model = request.env["kabay.deposit.declaration"]
        apartments = declaration_model.portal_apartments()
        selected = None
        if apartment_id:
            selected = next((apt for apt in apartments if str(apt["id"]) == str(apartment_id)), None)
        if not selected and len(apartments) == 1:
            selected = apartments[0]
        invoices = declaration_model.portal_invoice_options(selected["id"]) if selected else []
        return {
            "page_name": "kabay_deposit_new",
            "apartments": apartments,
            "selected_apartment_id": selected["id"] if selected else False,
            "invoices": invoices,
            "error": error,
            "form_data": form_data or {},
        }

    @http.route("/my/kabay/deposits", type="http", auth="user", website=True, methods=["GET"])
    def declarations(self, **kwargs):
        self._check_portal_user()
        records = request.env["kabay.deposit.declaration"].search([], order="deposit_date desc, id desc")
        return request.render("kabay_deposits.portal_deposit_list", {
            "page_name": "kabay_deposits",
            "declarations": records,
        })

    @http.route("/my/kabay/deposits/new", type="http", auth="user", website=True, methods=["GET"])
    def new_declaration(self, apartment_id=None, **kwargs):
        self._check_portal_user()
        return request.render("kabay_deposits.portal_deposit_form", self._form_values(apartment_id))

    @http.route("/my/kabay/deposits/create", type="http", auth="user", website=True, methods=["POST"], csrf=True)
    def create_declaration(self, **post):
        self._check_portal_user()
        file_storage = request.httprequest.files.get("proof")
        form_data = {key: value for key, value in post.items() if key not in ("csrf_token",)}
        try:
            if not file_storage or not file_storage.filename:
                raise ValidationError(_("Adjunte el comprobante del depósito."))
            proof_data = file_storage.read()
            if not proof_data or len(proof_data) > 12 * 1024 * 1024:
                raise ValidationError(_("El comprobante debe tener contenido y no superar 12 MB."))
            amount = float(post.get("amount", "0"))
            if not math.isfinite(amount) or amount <= 0:
                raise ValidationError(_("El importe declarado debe ser mayor que cero."))
            deposit_date = fields.Date.to_date(post.get("deposit_date"))
            if not deposit_date:
                raise ValidationError(_("Indique la fecha del depósito."))
            apartment_id = int(post.get("apartment_id", "0"))
            options = request.env["kabay.deposit.declaration"].portal_invoice_options(apartment_id)
            allowed = {option["invoice_id"]: option for option in options}
            selected_ids = [int(value) for value in request.httprequest.form.getlist("invoice_id")]
            if not selected_ids or len(selected_ids) != len(set(selected_ids)):
                raise ValidationError(_("Seleccione facturas o cuotas sin duplicados."))
            allocations = []
            for invoice_id in selected_ids:
                if invoice_id not in allowed:
                    raise AccessError(_("Una de las facturas seleccionadas no está autorizada para este apartamento."))
                allocation_amount = float(post.get("allocation_amount_%s" % invoice_id, "0"))
                if not math.isfinite(allocation_amount) or allocation_amount <= 0:
                    raise ValidationError(_("Indique un importe positivo para cada factura seleccionada."))
                allocations.append((0, 0, {"invoice_id": invoice_id, "amount": allocation_amount}))
            declaration_model = request.env["kabay.deposit.declaration"]
            with request.env.cr.savepoint():
                declaration = declaration_model.create({
                    "apartment_id": apartment_id,
                    "deposit_date": deposit_date,
                    "amount": amount,
                    "bank_name": (post.get("bank_name") or "").strip(),
                    "reference": (post.get("reference") or "").strip(),
                    "proof": base64.b64encode(proof_data),
                    "proof_filename": file_storage.filename,
                    "resident_note": post.get("resident_note", ""),
                    "allocation_ids": allocations,
                })
                declaration.action_submit()
            return request.redirect("/my/kabay/deposits/%s" % declaration.id)
        except (AccessError, UserError, ValidationError, ValueError, TypeError) as error:
            return request.render("kabay_deposits.portal_deposit_form", self._form_values(
                post.get("apartment_id"), error=str(error), form_data=form_data,
            ))

    @http.route("/my/kabay/deposits/<int:declaration_id>", type="http", auth="user", website=True, methods=["GET"])
    def declaration_detail(self, declaration_id, **kwargs):
        self._check_portal_user()
        declaration = request.env["kabay.deposit.declaration"].browse(declaration_id).exists()
        if not declaration:
            raise NotFound()
        declaration.action_portal_open()
        return request.render("kabay_deposits.portal_deposit_detail", {
            "page_name": "kabay_deposit_detail",
            "declaration": declaration,
        })
