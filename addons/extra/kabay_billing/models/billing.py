from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from calendar import monthrange


PERIODICITIES = [
    ("monthly", "Mensual"), ("bimonthly", "Bimestral"),
    ("quarterly", "Trimestral"), ("yearly", "Anual"), ("single", "Cargo único"),
]
CONCEPTS = [
    ("maintenance", "Mantenimiento ordinario"), ("extraordinary", "Cuota extraordinaria"),
    ("measured", "Servicios medidos"), ("penalty", "Penalidad autorizada"),
    ("other", "Ajuste u otro cargo aprobado"),
]


class KabayFeeRule(models.Model):
    _name = "kabay.fee.rule"
    _description = "Regla de cobro Kabay"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "condominium_id, name"

    name = fields.Char(required=True, tracking=True, string="Nombre")
    condominium_id = fields.Many2one("kabay.condominium", required=True, ondelete="restrict", index=True, string="Condominio")
    building_id = fields.Many2one("kabay.building", ondelete="restrict", index=True, string="Edificio / torre")
    apartment_ids = fields.Many2many("kabay.apartment", string="Unidades específicas")
    company_id = fields.Many2one("res.company", related="condominium_id.company_id", store=True, readonly=True, index=True, string="Compañía")
    product_id = fields.Many2one("product.product", required=True, ondelete="restrict", string="Producto")
    concept = fields.Selection(CONCEPTS, required=True, default="maintenance", tracking=True, string="Concepto")
    amount = fields.Monetary(required=True, currency_field="currency_id", tracking=True, string="Importe")
    currency_id = fields.Many2one("res.currency", required=True, default=lambda self: self.env.company.currency_id, string="Moneda")
    periodicity = fields.Selection(PERIODICITIES, required=True, default="monthly", string="Periodicidad")
    date_start = fields.Date(required=True, default=fields.Date.context_today, string="Fecha de inicio")
    date_end = fields.Date(string="Fecha de fin")
    due_day = fields.Integer(string="Día de vencimiento", help="Vacío: se usa la fecha general del lote.")
    active = fields.Boolean(default=True, tracking=True, string="Activo")

    @api.constrains("building_id", "condominium_id", "apartment_ids", "date_start", "date_end", "amount", "due_day")
    def _check_rule(self):
        for rule in self:
            if rule.building_id and rule.building_id.condominium_id != rule.condominium_id:
                raise ValidationError(_("La torre debe pertenecer al condominio."))
            if any(a.condominium_id != rule.condominium_id for a in rule.apartment_ids):
                raise ValidationError(_("Todas las unidades deben pertenecer al condominio de la regla."))
            if rule.date_end and rule.date_end < rule.date_start:
                raise ValidationError(_("La fecha final no puede preceder la inicial."))
            # Odoo Integer uses 0 as the empty value for an optional integer field.
            if rule.amount <= 0 or (rule.due_day and not 1 <= rule.due_day <= 31):
                raise ValidationError(_("El importe debe ser positivo y el día de vencimiento, si se configura, debe estar entre 1 y 31."))

    def applies_to(self, apartment, period_start):
        self.ensure_one()
        return bool(self.active and self.date_start <= period_start and (not self.date_end or self.date_end >= period_start)
                    and (not self.building_id or self.building_id == apartment.building_id)
                    and (not self.apartment_ids or apartment in self.apartment_ids))

    def is_due_in_period(self, period_start, period_end):
        self.ensure_one()
        if self.date_start > period_end or (self.date_end and self.date_end < period_start):
            return False
        if self.periodicity == "single":
            return period_start <= self.date_start <= period_end
        month_delta = (period_start.year - self.date_start.year) * 12 + period_start.month - self.date_start.month
        interval = {"monthly": 1, "bimonthly": 2, "quarterly": 3, "yearly": 12}[self.periodicity]
        return month_delta >= 0 and month_delta % interval == 0

    def get_due_date(self, period_start, fallback_date):
        self.ensure_one()
        if not self.due_day:
            return fallback_date
        last_day = monthrange(period_start.year, period_start.month)[1]
        return period_start.replace(day=min(self.due_day, last_day))


class KabayPaymentResponsibility(models.Model):
    _name = "kabay.payment.responsibility"
    _description = "Responsable histórico de pago"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "apartment_id, date_start desc, id desc"

    apartment_id = fields.Many2one("kabay.apartment", required=True, ondelete="restrict", index=True, string="Apartamento")
    condominium_id = fields.Many2one(related="apartment_id.condominium_id", store=True, index=True, string="Condominio")
    company_id = fields.Many2one(related="apartment_id.company_id", store=True, index=True, string="Compañía")
    fee_rule_id = fields.Many2one("kabay.fee.rule", ondelete="restrict", index=True, string="Regla de cuota")
    partner_id = fields.Many2one("res.partner", required=True, ondelete="restrict", index=True, string="Contacto")
    date_start = fields.Date(required=True, default=fields.Date.context_today, string="Fecha de inicio")
    date_end = fields.Date(string="Fecha de fin")
    state = fields.Selection([("draft", "Borrador"), ("confirmed", "Confirmado"), ("ended", "Finalizado")], default="confirmed", required=True, tracking=True, string="Estado")
    active = fields.Boolean(default=True, string="Activo")

    @api.constrains("apartment_id", "fee_rule_id", "partner_id", "date_start", "date_end")
    def _check_responsibility(self):
        for rec in self:
            if rec.fee_rule_id and rec.fee_rule_id.condominium_id != rec.apartment_id.condominium_id:
                raise ValidationError(_("La regla y la unidad deben pertenecer al mismo condominio."))
            if rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError(_("La fecha final no puede preceder la inicial."))
            if rec.partner_id.company_id and rec.apartment_id.company_id and rec.partner_id.company_id != rec.apartment_id.company_id:
                raise ValidationError(_("El contacto pertenece a otra compañía."))

    @api.model
    def find_for(self, apartment, rule, on_date):
        domain = [("apartment_id", "=", apartment.id), ("state", "=", "confirmed"), ("active", "=", True),
                  ("date_start", "<=", on_date), "|", ("date_end", "=", False), ("date_end", ">=", on_date),
                  "|", ("fee_rule_id", "=", rule.id), ("fee_rule_id", "=", False)]
        return self.search(domain)

    def write(self, vals):
        if any(rec.state == "confirmed" for rec in self):
            if not self.env.user.has_group("kabay_base.group_kabay_finance"):
                raise UserError(_("Solo Finanzas puede modificar responsabilidades confirmadas."))
            protected = {"apartment_id", "fee_rule_id", "partner_id", "date_start"}
            if protected.intersection(vals):
                raise UserError(_("Cierre el responsable y cree otro registro para conservar el historial."))
        if any(rec.state == "ended" for rec in self):
            raise UserError(_("Una responsabilidad finalizada es histórica y no se puede modificar."))
        return super().write(vals)


class KabayBillingBatch(models.Model):
    _name = "kabay.billing.batch"
    _description = "Lote de facturación Kabay"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "invoice_date desc, id desc"

    name = fields.Char(default="Nuevo", required=True, copy=False, readonly=True, string="Nombre")
    condominium_id = fields.Many2one("kabay.condominium", required=True, ondelete="restrict", index=True, string="Condominio")
    company_id = fields.Many2one(related="condominium_id.company_id", store=True, readonly=True, index=True, string="Compañía")
    period_start = fields.Date(required=True, default=fields.Date.context_today, string="Inicio del período")
    period_end = fields.Date(required=True, default=fields.Date.context_today, string="Fin del período")
    invoice_date = fields.Date(required=True, default=fields.Date.context_today, string="Fecha de factura")
    due_date = fields.Date(required=True, default=fields.Date.context_today, string="Fecha de vencimiento")
    fee_rule_ids = fields.Many2many("kabay.fee.rule", string="Reglas aplicables")
    line_ids = fields.One2many("kabay.billing.batch.line", "batch_id", string="Vista previa")
    state = fields.Selection([("draft", "Borrador"), ("prepared", "Preparado"), ("confirmed", "Confirmado"), ("cancelled", "Cancelado")], default="draft", required=True, tracking=True, string="Estado")
    ready_count = fields.Integer(compute="_compute_totals", string="Líneas listas")
    invoice_count = fields.Integer(compute="_compute_totals", string="Cantidad de facturas")
    total_expected = fields.Monetary(compute="_compute_totals", currency_field="currency_id", string="Total esperado")
    currency_id = fields.Many2one(related="company_id.currency_id", string="Moneda")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Nuevo") == "Nuevo":
                vals["name"] = self.env["ir.sequence"].next_by_code("kabay.billing.batch") or "Nuevo"
            vals["state"] = "draft"
        return super().create(vals_list)

    def write(self, vals):
        if "state" in vals or "line_ids" in vals:
            raise UserError(_("El estado y la vista previa del lote solo cambian mediante las acciones autorizadas."))
        protected = {"condominium_id", "period_start", "period_end", "invoice_date", "due_date", "fee_rule_ids"}
        if protected.intersection(vals) and any(batch.state != "draft" for batch in self):
            raise UserError(_("La configuración de un lote preparado queda congelada; vuelva a borrador mediante el flujo autorizado."))
        return super().write(vals)

    def _set_state(self, state):
        return super(KabayBillingBatch, self).write({"state": state})

    def _check_finance_access(self):
        if not self.env.is_system() and not self.env.user.has_group("kabay_base.group_kabay_finance"):
            raise AccessError(_("Solo Finanzas puede preparar o confirmar lotes de facturación."))

    @api.depends("line_ids.status", "line_ids.amount", "line_ids.move_id")
    def _compute_totals(self):
        for batch in self:
            batch.ready_count = len(batch.line_ids.filtered(lambda l: l.status == "ready"))
            batch.invoice_count = len(batch.line_ids.mapped("move_id"))
            batch.total_expected = sum(batch.line_ids.filtered(lambda l: l.status == "ready").mapped("amount"))

    def action_prepare(self):
        self._check_finance_access()
        for batch in self:
            if batch.state not in ("draft", "prepared"):
                raise UserError(_("Solo se puede preparar un lote en borrador."))
            if batch.period_end < batch.period_start:
                raise UserError(_("La fecha final del período no puede preceder la inicial."))
            batch.line_ids._unlink_from_batch_action()
            apartments = self.env["kabay.apartment"].search([("condominium_id", "=", batch.condominium_id.id), ("active", "=", True)])
            rules = batch.fee_rule_ids.filtered(lambda r: r.condominium_id == batch.condominium_id)
            if not rules:
                rules = self.env["kabay.fee.rule"].search([("condominium_id", "=", batch.condominium_id.id), ("active", "=", True)])
            rules = rules.filtered(lambda r: r.active and r.is_due_in_period(batch.period_start, batch.period_end))
            if not rules:
                for apartment in apartments:
                    self.env["kabay.billing.batch.line"]._create_from_batch_action({"batch_id": batch.id, "apartment_id": apartment.id, "status": "no_fee", "message": _("Sin tarifa aplicable")})
            for apartment in apartments:
                applicable = rules.filtered(lambda r: r.applies_to(apartment, batch.period_start))
                if not applicable:
                    self.env["kabay.billing.batch.line"]._create_from_batch_action({"batch_id": batch.id, "apartment_id": apartment.id, "status": "no_fee", "message": _("Sin tarifa aplicable")})
                    continue
                for rule in applicable:
                    resp = self.env["kabay.payment.responsibility"].find_for(apartment, rule, batch.period_start)
                    if len(resp) != 1:
                        status = "no_responsible" if not resp else "error"
                        message = _("Sin responsable configurado") if not resp else _("Hay varios responsables vigentes")
                        self.env["kabay.billing.batch.line"]._create_from_batch_action({"batch_id": batch.id, "apartment_id": apartment.id, "fee_rule_id": rule.id, "status": status, "message": message})
                        continue
                    company = batch.condominium_id.company_id
                    journal = self.env["account.journal"].search([("company_id", "=", company.id), ("type", "=", "sale")], limit=1) if company else False
                    # Product income accounts and taxes are company-dependent.
                    # Resolve them in the billing company's context, which may
                    # differ from the currently selected company of the user.
                    product = rule.product_id.with_company(company) if company else rule.product_id
                    account = product.property_account_income_id or product.categ_id.property_account_income_categ_id
                    rule_due_date = rule.get_due_date(batch.period_start, batch.due_date)
                    errors = []
                    if not company: errors.append(_("Condominio sin empresa facturadora"))
                    if company and company.country_id and company.country_id.code != "DO": errors.append(_("La empresa no está configurada para República Dominicana"))
                    if company and company.currency_id.name != "DOP": errors.append(_("La moneda de la empresa no es DOP"))
                    if not journal: errors.append(_("Falta diario de ventas"))
                    if not account: errors.append(_("Producto sin cuenta de ingresos"))
                    if rule.currency_id != company.currency_id if company else True: errors.append(_("Moneda de regla distinta de la compañía"))
                    if rule_due_date < batch.invoice_date: errors.append(_("El vencimiento es anterior a la fecha de emisión"))
                    self.env["kabay.billing.batch.line"]._create_from_batch_action({"batch_id": batch.id, "apartment_id": apartment.id, "fee_rule_id": rule.id,
                        "responsibility_id": resp.id, "partner_id": resp.partner_id.id, "amount": rule.amount, "due_date": rule_due_date,
                        "status": "error" if errors else "ready", "message": "; ".join(errors)})
            ready = batch.line_ids.filtered(lambda l: l.status == "ready")
            groups = {}
            for line in ready:
                group_key = (line.apartment_id.id, line.partner_id.id, line.company_id.id, line.due_date)
                groups.setdefault(group_key, self.env["kabay.billing.batch.line"])
                groups[group_key] |= line
            for lines in groups.values():
                for line in lines:
                    existing_line = self.env["account.move.line"].search([
                        ("kabay_apartment_id", "=", line.apartment_id.id), ("kabay_fee_rule_id", "=", line.fee_rule_id.id),
                        ("move_id.kabay_responsible_id", "=", line.partner_id.id), ("move_id.company_id", "=", batch.company_id.id),
                        ("move_id.kabay_period_start", "=", batch.period_start), ("move_id.kabay_period_end", "=", batch.period_end),
                        ("move_id.state", "!=", "cancel"),
                    ], limit=1)
                    if existing_line:
                        line._write_from_batch_action({"status": "duplicate", "message": _("Regla ya facturada: %s", existing_line.move_id.name)})
            batch._set_state("prepared")
        return True

    def action_confirm(self):
        self._check_finance_access()
        Move = self.env["account.move"]
        for batch in self:
            if batch.state != "prepared":
                raise UserError(_("Prepare primero el lote."))
            bad = batch.line_ids.filtered(lambda l: l.status in ("error", "no_fee", "no_responsible", "duplicate"))
            if bad:
                raise UserError(_("Corrija todos los errores de la vista previa antes de confirmar."))
            ready = batch.line_ids.filtered(lambda l: l.status == "ready")
            groups = {}
            for line in ready:
                group_key = (line.apartment_id.id, line.partner_id.id, line.company_id.id, line.due_date)
                groups.setdefault(group_key, self.env["kabay.billing.batch.line"])
                groups[group_key] |= line
            for lines in groups.values():
                first = lines[0]
                already_generated = self.env["account.move.line"].search([
                    ("kabay_apartment_id", "=", first.apartment_id.id), ("kabay_fee_rule_id", "in", lines.mapped("fee_rule_id").ids),
                    ("move_id.kabay_responsible_id", "=", first.partner_id.id), ("move_id.company_id", "=", batch.company_id.id),
                    ("move_id.kabay_period_start", "=", batch.period_start), ("move_id.kabay_period_end", "=", batch.period_end),
                    ("move_id.move_type", "=", "out_invoice"), ("move_id.state", "!=", "cancel"),
                ], limit=1)
                if already_generated:
                    raise UserError(_("La regla %s ya tiene una factura para este período.", already_generated.kabay_fee_rule_id.display_name))
                rule_ids = sorted(lines.mapped("fee_rule_id").ids)
                key = "%s:%s:%s:%s:%s:%s" % (first.apartment_id.id, first.partner_id.id, batch.company_id.id, ",".join(map(str, rule_ids)), batch.period_start, batch.period_end)
                existing = Move.search([("kabay_billing_key", "=", key), ("state", "!=", "cancel")], limit=1)
                if existing:
                    lines._write_from_batch_action({"status": "duplicate", "message": _("Factura ya generada: %s", existing.name)})
                    raise UserError(_("Se detectó una factura existente; vuelva a preparar el lote."))
                invoice_lines = []
                for line in lines:
                    product = line.fee_rule_id.product_id.with_company(batch.company_id)
                    account = product.property_account_income_id or product.categ_id.property_account_income_categ_id
                    taxes = product.taxes_id.filtered(lambda t: t.company_id == batch.company_id)
                    invoice_lines.append((0, 0, {"name": line.fee_rule_id.name, "product_id": product.id, "quantity": 1,
                        "price_unit": line.amount, "account_id": account.id, "tax_ids": [(6, 0, taxes.ids)],
                        "kabay_fee_rule_id": line.fee_rule_id.id, "kabay_apartment_id": line.apartment_id.id}))
                journal = self.env["account.journal"].search([("company_id", "=", batch.company_id.id), ("type", "=", "sale")], limit=1)
                move = Move.create({
                    "move_type": "out_invoice", "company_id": batch.company_id.id, "journal_id": journal.id,
                    "partner_id": first.partner_id.id, "invoice_date": batch.invoice_date, "invoice_date_due": first.due_date,
                    "kabay_condominium_id": batch.condominium_id.id, "kabay_apartment_id": first.apartment_id.id,
                    "kabay_responsible_id": first.partner_id.id, "kabay_batch_id": batch.id,
                    "kabay_period_start": batch.period_start, "kabay_period_end": batch.period_end,
                    "kabay_billing_key": key,
                    "invoice_line_ids": invoice_lines,
                })
                lines._write_from_batch_action({"status": "invoiced", "move_id": move.id})
            batch._set_state("confirmed")
        return True


class KabayBillingBatchLine(models.Model):
    _name = "kabay.billing.batch.line"
    _description = "Línea de vista previa Kabay"
    _order = "batch_id, apartment_id, id"

    batch_id = fields.Many2one("kabay.billing.batch", required=True, ondelete="cascade", index=True, string="Lote de facturación")
    condominium_id = fields.Many2one(related="batch_id.condominium_id", store=True, index=True, string="Condominio")
    company_id = fields.Many2one(related="batch_id.company_id", store=True, index=True, string="Compañía")
    apartment_id = fields.Many2one("kabay.apartment", required=True, ondelete="restrict", index=True, string="Apartamento")
    fee_rule_id = fields.Many2one("kabay.fee.rule", ondelete="restrict", string="Regla de cuota")
    responsibility_id = fields.Many2one("kabay.payment.responsibility", ondelete="restrict", string="Responsabilidad de pago")
    partner_id = fields.Many2one("res.partner", ondelete="restrict", string="Contacto")
    amount = fields.Monetary(currency_field="currency_id", string="Importe")
    currency_id = fields.Many2one(related="batch_id.company_id.currency_id", string="Moneda")
    due_date = fields.Date(string="Fecha de vencimiento")
    status = fields.Selection([("ready", "Lista"), ("no_fee", "Sin tarifa"), ("no_responsible", "Sin responsable"), ("duplicate", "Duplicada"), ("error", "Error"), ("invoiced", "Facturada")], required=True, index=True, string="Estado")
    message = fields.Char(string="Mensaje")
    move_id = fields.Many2one("account.move", ondelete="restrict", string="Asiento contable")

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(_("Las líneas se generan únicamente al preparar el lote de facturación."))

    @api.model
    def _create_from_batch_action(self, vals_list):
        if not self.env.is_system() and not self.env.user.has_group("kabay_base.group_kabay_finance"):
            raise AccessError(_("Solo Finanzas puede preparar líneas de facturación."))
        return super(KabayBillingBatchLine, self).create(vals_list)

    def write(self, vals):
        raise AccessError(_("La vista previa no se puede editar directamente; vuelva a preparar el lote."))

    def _write_from_batch_action(self, vals):
        if not self.env.is_system() and not self.env.user.has_group("kabay_base.group_kabay_finance"):
            raise AccessError(_("Solo Finanzas puede actualizar el resultado de la preparación del lote."))
        return super(KabayBillingBatchLine, self).write(vals)

    def unlink(self):
        raise AccessError(_("Las líneas solo se sustituyen al volver a preparar el lote."))

    def _unlink_from_batch_action(self):
        if not self.env.is_system() and not self.env.user.has_group("kabay_base.group_kabay_finance"):
            raise AccessError(_("Solo Finanzas puede regenerar la vista previa del lote."))
        # This internal operation only deletes the exact preview rows for a
        # finance-authorized prepare action; Finance has no general unlink ACL.
        return super(KabayBillingBatchLine, self.sudo()).unlink()


class AccountMove(models.Model):
    _inherit = "account.move"

    kabay_condominium_id = fields.Many2one("kabay.condominium", copy=False, ondelete="restrict", index=True, check_company=True, string="Condominio")
    kabay_apartment_id = fields.Many2one("kabay.apartment", copy=False, ondelete="restrict", index=True, check_company=True, string="Apartamento")
    kabay_responsible_id = fields.Many2one("res.partner", copy=False, ondelete="restrict", index=True, string="Responsable de pago")
    kabay_batch_id = fields.Many2one("kabay.billing.batch", copy=False, ondelete="restrict", index=True, string="Lote de facturación")
    kabay_period_start = fields.Date(copy=False, index=True, string="Inicio del período")
    kabay_period_end = fields.Date(copy=False, index=True, string="Fin del período")
    kabay_billing_key = fields.Char(copy=False, index=True, string="Clave de facturación")
    _kabay_billing_key_uniq = models.Constraint("unique(kabay_billing_key)", "La factura Kabay ya fue generada.")

    @api.constrains(
        "company_id", "partner_id", "kabay_condominium_id", "kabay_apartment_id",
        "kabay_responsible_id", "kabay_batch_id", "kabay_period_start", "kabay_period_end",
    )
    def _check_kabay_billing_identity(self):
        for move in self:
            apartment = move.kabay_apartment_id
            condominium = move.kabay_condominium_id
            batch = move.kabay_batch_id
            if apartment and (
                apartment.company_id != move.company_id
                or (condominium and apartment.condominium_id != condominium)
            ):
                raise ValidationError(_("La unidad de la factura debe pertenecer a su compañía y condominio."))
            if condominium and condominium.company_id != move.company_id:
                raise ValidationError(_("El condominio de la factura debe pertenecer a su compañía."))
            if move.kabay_responsible_id and move.partner_id != move.kabay_responsible_id:
                raise ValidationError(_("El contacto contable debe coincidir con el responsable histórico de la factura."))
            if batch and (
                batch.company_id != move.company_id
                or batch.condominium_id != condominium
                or batch.period_start != move.kabay_period_start
                or batch.period_end != move.kabay_period_end
            ):
                raise ValidationError(_("La factura debe conservar la compañía y el período de su lote Kabay."))

    def write(self, vals):
        identity_fields = {
            "kabay_condominium_id", "kabay_apartment_id", "kabay_responsible_id", "kabay_batch_id",
            "kabay_period_start", "kabay_period_end", "kabay_billing_key",
        }
        if identity_fields.intersection(vals) and any(move.state == "posted" for move in self):
            raise UserError(_("La identidad y trazabilidad Kabay de una factura publicada es histórica."))
        return super().write(vals)


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    kabay_fee_rule_id = fields.Many2one("kabay.fee.rule", copy=False, ondelete="restrict", index=True, check_company=True, string="Regla de cuota")
    kabay_apartment_id = fields.Many2one("kabay.apartment", copy=False, ondelete="restrict", index=True, check_company=True, string="Apartamento")

    @api.constrains("move_id", "kabay_fee_rule_id", "kabay_apartment_id")
    def _check_kabay_billing_line_identity(self):
        for line in self:
            if line.kabay_apartment_id and (
                line.move_id.kabay_apartment_id != line.kabay_apartment_id
                or line.move_id.company_id != line.kabay_apartment_id.company_id
            ):
                raise ValidationError(_("La línea de factura debe conservar la unidad y compañía Kabay."))
            if line.kabay_fee_rule_id and line.kabay_apartment_id and (
                line.kabay_fee_rule_id.condominium_id != line.kabay_apartment_id.condominium_id
            ):
                raise ValidationError(_("La regla de cuota y la unidad deben pertenecer al mismo condominio."))

    def write(self, vals):
        if {"kabay_fee_rule_id", "kabay_apartment_id"}.intersection(vals) and any(
            line.move_id.state == "posted" for line in self
        ):
            raise UserError(_("La asignación Kabay de una línea publicada es histórica."))
        return super().write(vals)
