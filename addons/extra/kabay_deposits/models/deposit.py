import re
import unicodedata

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_compare


DEPOSIT_STATES = [
    ("draft", "Borrador"),
    ("submitted", "Enviado"),
    ("reviewing", "En revisión"),
    ("verified", "Verificado"),
    ("applied", "Aplicado"),
    ("rejected", "Rechazado"),
    ("cancelled", "Cancelado"),
]
ACTIVE_DECLARATION_STATES = ("submitted", "reviewing", "verified", "applied")


class KabayDepositDeclaration(models.Model):
    _name = "kabay.deposit.declaration"
    _description = "Declaración de depósito Kabay"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "deposit_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(string="Número", required=True, default="Nuevo", copy=False, index=True, tracking=True)
    apartment_id = fields.Many2one("kabay.apartment", required=True, ondelete="restrict", index=True, tracking=True, string="Apartamento")
    apartment_label = fields.Char(string="Nombre de unidad", related="apartment_id.name", store=True)
    condominium_id = fields.Many2one(related="apartment_id.condominium_id", store=True, index=True, string="Condominio")
    company_id = fields.Many2one(related="apartment_id.company_id", store=True, index=True, string="Compañía")
    currency_id = fields.Many2one(related="company_id.currency_id", store=True, string="Moneda")
    declarant_partner_id = fields.Many2one("res.partner", required=True, ondelete="restrict", index=True, tracking=True, string="Residente declarante")
    deposit_date = fields.Date(required=True, default=fields.Date.context_today, tracking=True, string="Fecha del depósito")
    amount = fields.Monetary(required=True, currency_field="currency_id", tracking=True, string="Importe")
    bank_name = fields.Char(required=True, tracking=True, string="Banco")
    destination_bank_id = fields.Many2one("res.partner.bank", string="Cuenta receptora", ondelete="restrict", check_company=True)
    reference = fields.Char(string="Referencia / autorización", required=True, tracking=True, index=True)
    proof = fields.Binary(string="Comprobante", attachment=True, required=True)
    proof_filename = fields.Char(string="Nombre del comprobante")
    resident_note = fields.Text(string="Observaciones del residente")
    allocation_ids = fields.One2many("kabay.deposit.allocation", "declaration_id", string="Facturas / cuotas declaradas")
    allocated_amount = fields.Monetary(compute="_compute_allocated_amount", currency_field="currency_id", string="Importe imputado")
    state = fields.Selection(DEPOSIT_STATES, default="draft", required=True, index=True, tracking=True, string="Estado")
    portal_state_label = fields.Char(compute="_compute_portal_state_label", string="Estado en el portal")
    reviewer_id = fields.Many2one("res.users", string="Responsable de revisión", readonly=True, tracking=True)
    reviewed_at = fields.Datetime(string="Fecha de revisión", readonly=True, tracking=True)
    rejected_by_id = fields.Many2one("res.users", string="Rechazado por", readonly=True, tracking=True)
    rejected_at = fields.Datetime(string="Fecha de rechazo", readonly=True, tracking=True)
    rejection_reason = fields.Text(string="Motivo del rechazo", readonly=True, tracking=True)
    statement_line_id = fields.Many2one("account.bank.statement.line", string="Movimiento bancario", ondelete="restrict", check_company=True, copy=False, tracking=True)
    statement_journal_id = fields.Many2one(related="statement_line_id.journal_id", string="Diario bancario")
    payment_ids = fields.Many2many("account.payment", compute="_compute_payment_ids", string="Pagos contables")
    applied_at = fields.Datetime(string="Fecha de aplicación", readonly=True, tracking=True)

    _name_uniq = models.Constraint("unique(name)", "El número de declaración debe ser único.")
    _statement_line_uniq = models.Constraint("unique(statement_line_id)", "Una línea de extracto solo puede verificarse para una declaración.")

    @api.model_create_multi
    def create(self, vals_list):
        is_portal = self.env.user.has_group("base.group_portal") and not self.env.is_system()
        for vals in vals_list:
            if vals.get("name", "Nuevo") == "Nuevo":
                vals["name"] = self.env["ir.sequence"].sudo().next_by_code("kabay.deposit.declaration") or "Nuevo"
            if is_portal:
                if vals.get("declarant_partner_id") and vals["declarant_partner_id"] != self.env.user.partner_id.id:
                    raise AccessError(_("Solo puede declarar depósitos para su propio contacto."))
                vals["declarant_partner_id"] = self.env.user.partner_id.id
                vals["state"] = "draft"
                vals.pop("reviewer_id", None)
                vals.pop("reviewed_at", None)
                vals.pop("rejected_by_id", None)
                vals.pop("rejected_at", None)
                vals.pop("rejection_reason", None)
                vals.pop("applied_at", None)
                vals.pop("statement_line_id", None)
                vals.pop("payment_ids", None)
            child_commands = vals.get("allocation_ids", [])
            if vals.get("payment_ids") or any(
                isinstance(command, (list, tuple)) and len(command) > 2
                and command[0] == 0 and isinstance(command[2], dict) and command[2].get("payment_id")
                for command in child_commands
            ):
                raise UserError(_("Los pagos solo se generan desde la acción de aplicación contable."))
        declarations = super().create(vals_list)
        for declaration in declarations:
            declaration._check_resident_access()
            declaration._check_declaration_values(check_allocations=True)
        return declarations

    def write(self, vals):
        forbidden = {
            "name", "state", "declarant_partner_id", "reviewer_id", "reviewed_at", "rejected_by_id",
            "rejected_at", "rejection_reason", "payment_ids", "applied_at",
        }
        if forbidden.intersection(vals):
            raise UserError(_("Use las acciones disponibles para cambiar el estado o los datos de auditoría."))
        if "statement_line_id" in vals:
            if set(vals) != {"statement_line_id"}:
                raise UserError(_("Vincule el movimiento por separado durante la revisión."))
            if not self.env.user.has_group("kabay_base.group_kabay_finance"):
                raise AccessError(_("Solo Finanzas puede vincular un movimiento bancario."))
            for declaration in self:
                if declaration.state != "reviewing":
                    raise UserError(_("El movimiento bancario se vincula durante la revisión."))
                candidate = self.env["account.bank.statement.line"].browse(vals["statement_line_id"]).exists()
                declaration._check_bank_match(candidate, require_unreconciled=True)
            return super().write(vals)
        if any(record.state != "draft" for record in self):
            raise UserError(_("La declaración queda bloqueada al enviarse. Use el flujo de revisión para continuar."))
        if self.env.user.has_group("base.group_portal"):
            if any(record.declarant_partner_id != self.env.user.partner_id for record in self):
                raise AccessError(_("No puede modificar declaraciones de otra persona."))
        result = super().write(vals)
        for declaration in self:
            declaration._check_resident_access()
            declaration._check_declaration_values(check_allocations=True)
        return result

    @api.depends("allocation_ids.amount", "allocation_ids.invoice_id")
    def _compute_allocated_amount(self):
        for declaration in self:
            declaration.allocated_amount = sum(declaration.allocation_ids.mapped("amount"))

    @api.depends("allocation_ids.payment_id")
    def _compute_payment_ids(self):
        for declaration in self:
            declaration.payment_ids = declaration.allocation_ids.mapped("payment_id")

    @api.depends("state")
    def _compute_portal_state_label(self):
        selection = dict(self._fields["state"].selection)
        for declaration in self:
            declaration.portal_state_label = selection.get(declaration.state, "")

    def _check_finance_access(self):
        if not self.env.user.has_group("kabay_base.group_kabay_finance") and not self.env.is_system():
            raise AccessError(_("Solo Finanzas puede revisar, verificar o aplicar depósitos."))

    def _is_resident_portal_user(self):
        return self.env.user.has_group("kabay_deposits.group_kabay_deposit_resident")

    @api.model
    def _current_resident_apartments(self, partner):
        today = fields.Date.context_today(self)
        relations = self.env["kabay.apartment.relation"].search([
            ("partner_id", "=", partner.id), ("state", "=", "confirmed"), ("active", "=", True),
            ("role", "in", ["owner", "tenant", "authorized_resident"]), ("date_start", "<=", today),
            "|", ("date_end", "=", False), ("date_end", ">=", today),
        ])
        return relations.mapped("apartment_id")

    def _check_resident_access(self):
        self.ensure_one()
        apartments = self._current_resident_apartments(self.declarant_partner_id)
        if self.apartment_id.id not in apartments.ids:
            raise ValidationError(_("La persona declarante debe tener una relación residencial vigente y confirmada con el apartamento."))
        apartment = self.apartment_id.sudo()
        if apartment.company_id not in self.env.companies:
            raise ValidationError(_("La compañía del apartamento no está habilitada para el usuario."))

    @api.model
    def portal_apartments(self):
        if not self._is_resident_portal_user():
            raise AccessError(_("Esta consulta solo está disponible para residentes del portal."))
        apartments = self._current_resident_apartments(self.env.user.partner_id)
        return [{"id": apartment.id, "label": apartment.sudo().display_name} for apartment in apartments]

    @api.model
    def portal_invoice_options(self, apartment_id):
        if not self._is_resident_portal_user():
            raise AccessError(_("Esta consulta solo está disponible para residentes del portal."))
        partner = self.env.user.partner_id
        apartments = self._current_resident_apartments(partner)
        if int(apartment_id) not in apartments.ids:
            raise AccessError(_("No tiene acceso a ese apartamento."))
        apartment = apartments.filtered(lambda apt: apt.id == int(apartment_id)).sudo()
        if apartment.company_id not in self.env.companies:
            raise AccessError(_("La compañía del apartamento no está habilitada para este usuario."))
        # Restricted, read-only disclosure: only invoices for this resident's current
        # apartment/company are searched, and only the fields needed for an allocation
        # are returned. Portal users never receive account.move ACLs.
        moves = self.env["account.move"].sudo().search([
            ("company_id", "=", apartment.company_id.id), ("currency_id", "=", apartment.company_id.currency_id.id),
            ("move_type", "=", "out_invoice"), ("state", "=", "posted"), ("amount_residual", ">", 0),
            "|",
            "&", ("kabay_apartment_id", "=", apartment.id), ("kabay_responsible_id", "=", partner.id),
            "&", ("kabay_financing_apartment_id", "=", apartment.id), ("partner_id", "=", partner.id),
        ], order="invoice_date_due, id")
        options = []
        for move in moves:
            if not self._invoice_is_eligible(move, apartment, partner):
                continue
            installment = move.kabay_financing_installment_id
            label = move.name
            if installment:
                label = _("%s — cuota %s del contrato %s") % (move.name, installment.number, installment.contract_id.name)
            options.append({
                "invoice_id": move.id,
                "label": label,
                "due_date": fields.Date.to_string(move.invoice_date_due) if move.invoice_date_due else "",
                "residual": move.amount_residual,
                "currency": move.currency_id.name,
            })
        return options

    @api.model
    def _invoice_is_eligible(self, invoice, apartment, partner):
        invoice.ensure_one()
        if invoice.state != "posted" or invoice.move_type != "out_invoice" or invoice.amount_residual <= 0:
            return False
        if invoice.company_id != apartment.company_id or invoice.currency_id != apartment.company_id.currency_id:
            return False
        billing_match = invoice.kabay_apartment_id == apartment and invoice.kabay_responsible_id == partner and invoice.partner_id == partner
        installment = invoice.kabay_financing_installment_id
        financing_match = (
            invoice.kabay_financing_apartment_id == apartment
            and invoice.partner_id == partner
            and bool(installment)
            and installment.invoice_id == invoice
            and installment.contract_id.apartment_id == apartment
            and installment.contract_id.buyer_id == partner
        )
        return bool(billing_match or financing_match)

    def _validate_invoice(self, invoice_id, installment_id=False, amount=False, check_resident=True):
        self.ensure_one()
        if check_resident:
            self._check_resident_access()
        # Portal has standard read ACL on account.move, scoped by Odoo's native
        # personal-invoice rule. Keep this lookup read-only and validate its
        # apartment, partner, company, currency and state explicitly as well.
        # Staff Finance uses the same checks against this single move.
        invoice = self.env["account.move"].sudo().browse(invoice_id).exists()
        apartment = self.apartment_id.sudo()
        if not invoice or not self._invoice_is_eligible(invoice, apartment, self.declarant_partner_id):
            raise ValidationError(_("La factura no pertenece a este residente y apartamento, no está publicada o no tiene saldo pendiente."))
        if installment_id and invoice.kabay_financing_installment_id.id != int(installment_id):
            raise ValidationError(_("La cuota seleccionada no corresponde a la factura."))
        if amount:
            if amount <= 0 or float_compare(amount, invoice.amount_residual, precision_rounding=invoice.currency_id.rounding) > 0:
                raise ValidationError(_("El importe imputado debe ser positivo y no superar el saldo pendiente de la factura."))
        return invoice

    @api.constrains("apartment_id", "declarant_partner_id", "deposit_date", "amount", "bank_name", "reference", "destination_bank_id", "allocation_ids")
    def _check_declaration(self):
        for declaration in self:
            declaration._check_declaration_values(check_allocations=bool(declaration.allocation_ids))

    def _check_declaration_values(self, check_allocations=True, check_resident=True):
        self.ensure_one()
        if check_resident:
            self._check_resident_access()
        if self.amount <= 0:
            raise ValidationError(_("El importe declarado debe ser mayor que cero."))
        if not (self.bank_name or "").strip() or not (self.reference or "").strip():
            raise ValidationError(_("Indique el banco de origen y la referencia del depósito."))
        if self.destination_bank_id:
            bank = self.destination_bank_id
            if bank.company_id and bank.company_id != self.company_id:
                raise ValidationError(_("La cuenta bancaria receptora debe pertenecer a la compañía del apartamento."))
            if bank.partner_id != self.company_id.partner_id:
                raise ValidationError(_("La cuenta bancaria receptora debe estar registrada a nombre de la compañía."))
        if check_allocations:
            if not self.allocation_ids:
                raise ValidationError(_("Seleccione al menos una factura o cuota financiada."))
            total = sum(self.allocation_ids.mapped("amount"))
            if float_compare(total, self.amount, precision_rounding=self.currency_id.rounding) != 0:
                raise ValidationError(_("La suma imputada debe ser igual al importe declarado."))
            for allocation in self.allocation_ids:
                self._validate_invoice(allocation.invoice_id.id, allocation.installment_id.id, allocation.amount, check_resident=check_resident)
        if self.state in ACTIVE_DECLARATION_STATES:
            self._check_duplicate_declaration()

    def _check_duplicate_declaration(self):
        self.ensure_one()
        normalized = self._normalize_reference(self.reference)
        possible = self.search([
            ("id", "!=", self.id), ("company_id", "=", self.company_id.id),
            ("declarant_partner_id", "=", self.declarant_partner_id.id),
            ("deposit_date", "=", self.deposit_date), ("amount", "=", self.amount),
            ("state", "not in", ["rejected", "cancelled"]),
        ])
        if any(self._normalize_reference(item.reference) == normalized for item in possible):
            raise ValidationError(_("Ya existe una declaración con la misma fecha, importe y referencia."))

    @api.model
    def _normalize_reference(self, value):
        value = unicodedata.normalize("NFKC", value or "").casefold()
        return re.sub(r"[^a-z0-9]", "", value)

    def _transition(self, vals):
        return super(KabayDepositDeclaration, self).write(vals)

    def action_submit(self):
        for declaration in self:
            if declaration.state != "draft":
                raise UserError(_("Solo los borradores pueden enviarse."))
            if self._is_resident_portal_user() and declaration.declarant_partner_id != self.env.user.partner_id:
                raise AccessError(_("No puede enviar declaraciones de otra persona."))
            declaration._check_declaration_values(check_allocations=True)
            declaration._check_duplicate_declaration()
            declaration._transition({"state": "submitted"})
            declaration.message_post(body=_("Declaración enviada por %s.") % self.env.user.display_name)
        return True

    def action_start_review(self):
        self._check_finance_access()
        for declaration in self:
            if declaration.state != "submitted":
                raise UserError(_("Solo las declaraciones enviadas pueden pasar a revisión."))
            declaration._transition({"state": "reviewing", "reviewer_id": self.env.user.id, "reviewed_at": fields.Datetime.now()})
            declaration.message_post(body=_("Revisión iniciada por %s.") % self.env.user.display_name)
        return True

    def action_verify_bank_line(self):
        self._check_finance_access()
        for declaration in self:
            if declaration.state != "reviewing":
                raise UserError(_("La declaración debe estar en revisión para verificarse."))
            declaration._check_declaration_values(check_allocations=True, check_resident=False)
            declaration._check_bank_match(declaration.statement_line_id, require_unreconciled=True)
            declaration._transition({"state": "verified", "reviewer_id": self.env.user.id, "reviewed_at": fields.Datetime.now()})
            declaration.message_post(body=_("Movimiento bancario verificado por %s. No se ha creado ningún pago.") % self.env.user.display_name)
        return True

    def _check_bank_match(self, statement_line, require_unreconciled=True):
        self.ensure_one()
        if not statement_line:
            raise ValidationError(_("Seleccione una línea real de extracto bancario."))
        statement_line.ensure_one()
        if statement_line.journal_id.type != "bank" or statement_line.move_id.state != "posted":
            raise ValidationError(_("Seleccione una línea de extracto bancaria real y contabilizada."))
        if statement_line.company_id != self.company_id or statement_line.currency_id != self.currency_id:
            raise ValidationError(_("El movimiento bancario debe pertenecer a la misma compañía y moneda."))
        if statement_line.amount <= 0:
            raise ValidationError(_("El movimiento bancario debe ser un ingreso positivo."))
        if float_compare(statement_line.amount, self.amount, precision_rounding=self.currency_id.rounding) != 0:
            raise ValidationError(_("El importe del movimiento bancario no coincide con la declaración."))
        if statement_line.date and self.deposit_date and abs((statement_line.date - self.deposit_date).days) > 3:
            raise ValidationError(_("La fecha bancaria debe estar dentro de los tres días del depósito declarado."))
        expected_ref = self._normalize_reference(self.reference)
        actual_ref = self._normalize_reference(statement_line.payment_ref or "")
        if not expected_ref or expected_ref not in actual_ref:
            raise ValidationError(_("La referencia declarada no aparece en el concepto bancario."))
        if self.destination_bank_id and statement_line.journal_id.bank_account_id != self.destination_bank_id:
            raise ValidationError(_("El diario bancario no corresponde a la cuenta receptora declarada."))
        if require_unreconciled and statement_line.is_reconciled:
            raise ValidationError(_("La línea bancaria ya está conciliada y no puede aplicarse otra vez."))
        duplicate = self.search([("statement_line_id", "=", statement_line.id), ("id", "!=", self.id)], limit=1)
        if duplicate:
            raise ValidationError(_("Este movimiento bancario ya está vinculado a otra declaración."))
        return True

    def action_reject(self, reason):
        self._check_finance_access()
        reason = (reason or "").strip()
        if not reason:
            raise ValidationError(_("Indique el motivo del rechazo."))
        for declaration in self:
            if declaration.state not in ("submitted", "reviewing"):
                raise UserError(_("Solo se puede rechazar una declaración enviada o en revisión."))
            declaration._transition({
                "state": "rejected", "rejected_by_id": self.env.user.id,
                "rejected_at": fields.Datetime.now(), "rejection_reason": reason,
            })
            declaration.message_post(body=_("Declaración rechazada por %s: %s") % (self.env.user.display_name, reason))
        return True

    def action_open_reject_wizard(self):
        self.ensure_one()
        self._check_finance_access()
        if self.state not in ("submitted", "reviewing"):
            raise UserError(_("Solo se puede rechazar una declaración enviada o en revisión."))
        wizard = self.env["kabay.deposit.reject.wizard"].create({"declaration_id": self.id})
        return {
            "type": "ir.actions.act_window", "name": _("Motivo de rechazo"),
            "res_model": "kabay.deposit.reject.wizard", "res_id": wizard.id,
            "view_mode": "form", "target": "new",
        }

    def action_cancel(self):
        for declaration in self:
            if declaration.state in ("draft", "submitted"):
                if self._is_resident_portal_user() and declaration.declarant_partner_id != self.env.user.partner_id:
                    raise AccessError(_("No puede cancelar declaraciones de otra persona."))
            elif declaration.state in ("reviewing", "verified"):
                declaration._check_finance_access()
            else:
                raise UserError(_("Esta declaración ya no puede cancelarse."))
            declaration._transition({"state": "cancelled", "statement_line_id": False})
            declaration.message_post(body=_("Declaración cancelada por %s.") % self.env.user.display_name)
        return True

    def action_apply(self):
        self._check_finance_access()
        for declaration in self:
            if declaration.state != "verified":
                raise UserError(_("Solo una declaración verificada puede aplicarse."))
            declaration._check_declaration_values(check_allocations=True, check_resident=False)
            declaration._check_bank_match(declaration.statement_line_id, require_unreconciled=True)
            statement_line = declaration.statement_line_id
            aml_ids = []
            for allocation in declaration.allocation_ids.sorted(lambda item: item.invoice_id.id):
                invoice = declaration._validate_invoice(allocation.invoice_id.id, allocation.installment_id.id, allocation.amount, check_resident=False)
                if float_compare(allocation.amount, invoice.amount_residual, precision_rounding=invoice.currency_id.rounding) > 0:
                    raise UserError(_("El saldo de una factura cambió desde la verificación. Revise la imputación."))
                wizard = self.env["account.payment.register"].with_company(declaration.company_id).with_context(
                    active_model="account.move", active_ids=invoice.ids,
                ).create({
                    "amount": allocation.amount,
                    "payment_date": statement_line.date,
                    "journal_id": statement_line.journal_id.id,
                    "group_payment": False,
                    "communication": declaration.reference,
                })
                payments = wizard._create_payments()
                if len(payments) != 1:
                    raise UserError(_("Odoo no creó exactamente un pago para la imputación."))
                # The finance action above is the sole authorized path that links
                # the accounting payment; bypass resident-facing allocation ACLs.
                super(KabayDepositAllocation, allocation.sudo()).write({"payment_id": payments.id})
                payment_lines = payments.move_id.line_ids.filtered(
                    lambda line: line.account_id == payments.outstanding_account_id and not line.reconciled
                )
                if not payment_lines:
                    raise UserError(_("El pago no tiene un apunte pendiente de conciliación bancaria."))
                aml_ids.extend(payment_lines.ids)
            statement_line.set_line_bank_statement_line(aml_ids)
            statement_line.invalidate_recordset(["is_reconciled", "amount_residual"])
            if not statement_line.is_reconciled:
                raise UserError(_("Odoo no confirmó la conciliación completa del movimiento bancario; no se aplicó la declaración."))
            declaration._transition({"state": "applied", "applied_at": fields.Datetime.now()})
            declaration.message_post(body=_("Pagos creados y conciliación bancaria aplicada por %s mediante la Contabilidad estándar de Odoo.") % self.env.user.display_name)
        return True

    def action_portal_open(self):
        self.ensure_one()
        if not self._is_resident_portal_user() or self.declarant_partner_id != self.env.user.partner_id:
            raise AccessError(_("No tiene acceso a esta declaración."))
        return True


class KabayDepositAllocation(models.Model):
    _name = "kabay.deposit.allocation"
    _description = "Imputación de depósito Kabay"
    _order = "id"
    _check_company_auto = True

    declaration_id = fields.Many2one("kabay.deposit.declaration", required=True, ondelete="cascade", index=True, check_company=True, string="Declaración de depósito")
    company_id = fields.Many2one(related="declaration_id.company_id", store=True, index=True, string="Compañía")
    currency_id = fields.Many2one(related="declaration_id.currency_id", store=True, string="Moneda")
    invoice_id = fields.Many2one("account.move", string="Factura", required=True, ondelete="restrict", index=True, check_company=True)
    installment_id = fields.Many2one("kabay.financing.installment", string="Cuota de financiamiento", ondelete="restrict", check_company=True)
    amount = fields.Monetary(required=True, currency_field="currency_id", string="Importe")
    payment_id = fields.Many2one("account.payment", string="Pago contable", readonly=True, copy=False, ondelete="restrict", check_company=True)

    _invoice_per_declaration_uniq = models.Constraint("unique(declaration_id, invoice_id)", "La factura solo puede aparecer una vez en cada declaración.")
    _payment_uniq = models.Constraint("unique(payment_id)", "Un pago contable solo puede pertenecer a una imputación de depósito.")

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get("payment_id") for vals in vals_list):
            raise UserError(_("El pago se genera solo durante la aplicación contable."))
        if self.env.user.has_group("base.group_portal") and not self.env.is_system():
            for vals in vals_list:
                declaration = self.env["kabay.deposit.declaration"].browse(vals.get("declaration_id")).exists()
                if not declaration or declaration.declarant_partner_id != self.env.user.partner_id or declaration.state != "draft":
                    raise AccessError(_("Solo puede añadir imputaciones a su propio borrador."))
        return super().create(vals_list)

    def write(self, vals):
        if set(vals) == {"payment_id"}:
            raise UserError(_("El pago se enlaza solo durante la aplicación contable."))
        if "declaration_id" in vals or "payment_id" in vals:
            raise UserError(_("No puede cambiar el padre de la imputación ni vincular pagos manualmente."))
        if set(vals) - {"invoice_id", "installment_id", "amount"}:
            raise UserError(_("Solo puede corregir factura, cuota o importe en un borrador."))
        if any(line.declaration_id.state != "draft" for line in self):
            raise UserError(_("Las imputaciones quedan bloqueadas al enviar la declaración."))
        if self.env.user.has_group("base.group_portal"):
            if any(line.declaration_id.declarant_partner_id != self.env.user.partner_id for line in self):
                raise AccessError(_("No puede modificar imputaciones de otra persona."))
        return super().write(vals)

    def unlink(self):
        if any(line.declaration_id.state != "draft" for line in self):
            raise UserError(_("Las imputaciones quedan bloqueadas al enviar la declaración."))
        return super().unlink()

    @api.constrains("declaration_id", "invoice_id", "installment_id", "amount")
    def _check_allocation(self):
        for allocation in self:
            if allocation.amount <= 0:
                raise ValidationError(_("El importe de cada imputación debe ser mayor que cero."))
            allocation.declaration_id._validate_invoice(
                allocation.invoice_id.id, allocation.installment_id.id, allocation.amount,
            )
            if allocation.installment_id and allocation.installment_id.contract_id.apartment_id != allocation.declaration_id.apartment_id:
                raise ValidationError(_("La cuota debe pertenecer al apartamento declarado."))


class KabayDepositRejectWizard(models.TransientModel):
    _name = "kabay.deposit.reject.wizard"
    _description = "Motivo de rechazo de declaración de depósito"

    declaration_id = fields.Many2one("kabay.deposit.declaration", required=True, readonly=True, string="Declaración de depósito")
    reason = fields.Text(required=True, string="Motivo")

    def action_confirm(self):
        self.ensure_one()
        self.declaration_id.action_reject(self.reason)
        return {"type": "ir.actions.act_window_close"}


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    kabay_deposit_declaration_ids = fields.One2many(
        "kabay.deposit.declaration", "statement_line_id", string="Declaración Kabay vinculada"
    )


class AccountPayment(models.Model):
    _inherit = "account.payment"

    kabay_deposit_allocation_ids = fields.One2many(
        "kabay.deposit.allocation", "payment_id", string="Imputación de depósito Kabay"
    )
