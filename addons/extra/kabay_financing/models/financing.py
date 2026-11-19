from calendar import monthrange
from datetime import date, timedelta

from odoo import api, fields, models, _, Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_compare


FREQUENCIES = [
    ("monthly", "Mensual"),
    ("bimonthly", "Bimestral"),
    ("quarterly", "Trimestral"),
    ("yearly", "Anual"),
]


class KabayFinancingContract(models.Model):
    _name = "kabay.financing.contract"
    _description = "Contrato de compra financiada Kabay"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "start_date desc, name desc"

    name = fields.Char(string="Número de contrato", default="Nuevo", required=True, copy=False, tracking=True, index=True)
    condominium_id = fields.Many2one("kabay.condominium", required=True, ondelete="restrict", index=True, tracking=True, string="Condominio")
    building_id = fields.Many2one("kabay.building", related="apartment_id.building_id", store=True, index=True, string="Edificio / torre")
    apartment_id = fields.Many2one("kabay.apartment", required=True, ondelete="restrict", index=True, tracking=True, string="Apartamento")
    buyer_id = fields.Many2one("res.partner", required=True, ondelete="restrict", string="Comprador", tracking=True, index=True)
    creditor_id = fields.Many2one("res.partner", required=True, ondelete="restrict", string="Vendedor / acreedor", tracking=True, index=True)
    company_id = fields.Many2one("res.company", required=True, ondelete="restrict", string="Empresa facturadora", default=lambda self: self.env.company, tracking=True, index=True)
    currency_id = fields.Many2one("res.currency", required=True, default=lambda self: self.env.company.currency_id, tracking=True, string="Moneda")
    product_id = fields.Many2one("product.product", required=True, ondelete="restrict", string="Producto de facturación")
    purchase_price = fields.Monetary(required=True, currency_field="currency_id", tracking=True, string="Precio de compra")
    down_payment = fields.Monetary(required=True, currency_field="currency_id", tracking=True, string="Inicial")
    financed_amount = fields.Monetary(compute="_compute_amounts", store=True, currency_field="currency_id", string="Saldo financiado")
    installment_count = fields.Integer(required=True, default=1, tracking=True, string="Número de cuotas")
    frequency = fields.Selection(FREQUENCIES, required=True, default="monthly", tracking=True, string="Frecuencia de pago")
    installment_amount = fields.Monetary(compute="_compute_amounts", store=True, currency_field="currency_id", string="Cuota calculada")
    total_interest = fields.Monetary(compute="_compute_amounts", store=True, currency_field="currency_id", string="Interés total calculado")
    interest_rate = fields.Float(string="Tasa anual de interés (%)", default=0.0, digits=(8, 4), tracking=True,
        help="Tasa anual nominal. El sistema calcula las cuotas amortizadas sobre saldo insoluto.")
    interest_method = fields.Char(compute="_compute_interest_method", store=True, string="Método de interés (automático)")
    grace_days = fields.Integer(string="Días calendario de gracia", default=5, required=True, tracking=True,
        help="Días después del vencimiento antes de marcar el saldo como mora. No genera un cargo financiero.")
    start_date = fields.Date(required=True, tracking=True, string="Fecha de inicio")
    due_day = fields.Integer(string="Día de vencimiento", help="Vacío: se usa el día de start_date. Valores admitidos: 1–31.")
    invoice_lead_days = fields.Integer(string="Generar borrador días antes", default=30, required=True,
        help="El botón de generación crea borradores dentro de este horizonte; nunca publica ni cobra.")
    state = fields.Selection([
        ("draft", "Borrador"), ("active", "Activo"), ("suspended", "Suspendido"), ("cancelled", "Cancelado"),
    ], default="draft", required=True, tracking=True, index=True, string="Estado")
    installment_ids = fields.One2many("kabay.financing.installment", "contract_id", string="Calendario de cuotas")
    invoice_ids = fields.One2many("account.move", "kabay_financing_contract_id", string="Facturas relacionadas")
    note = fields.Text(string="Observaciones")

    total_installments = fields.Integer(string="Cantidad de cuotas", compute="_compute_progress")
    paid_installments = fields.Integer(compute="_compute_progress", string="Cuotas pagadas")
    pending_installments = fields.Integer(compute="_compute_progress", string="Cuotas pendientes")
    overdue_installments = fields.Integer(compute="_compute_progress", string="Cuotas vencidas")
    partial_installments = fields.Integer(compute="_compute_progress", string="Cuotas parcialmente pagadas")
    draft_installments = fields.Integer(compute="_compute_progress", string="Cuotas con factura borrador")
    total_paid = fields.Monetary(compute="_compute_progress", currency_field="currency_id", string="Total abonado según Contabilidad")
    account_residual = fields.Monetary(compute="_compute_progress", currency_field="currency_id", string="Saldo de facturas según Contabilidad")
    scheduled_principal = fields.Monetary(compute="_compute_progress", currency_field="currency_id", string="Capital aún no facturado")
    next_due_date = fields.Date(compute="_compute_progress", string="Próximo vencimiento")
    progress_label = fields.Char(compute="_compute_progress", string="Progreso")

    _name_uniq = models.Constraint("unique(name)", "El número de contrato debe ser único.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Nuevo") == "Nuevo":
                vals["name"] = self.env["ir.sequence"].next_by_code("kabay.financing.contract") or "Nuevo"
        return super().create(vals_list)

    @api.depends("purchase_price", "down_payment", "installment_count", "frequency", "interest_rate", "currency_id")
    def _compute_amounts(self):
        for contract in self:
            financed = max(contract.purchase_price - contract.down_payment, 0.0)
            contract.financed_amount = financed
            periods_per_year = {"monthly": 12, "bimonthly": 6, "quarterly": 4, "yearly": 1}.get(contract.frequency, 12)
            periodic_rate = contract.interest_rate / 100.0 / periods_per_year
            if not contract.installment_count or not contract.currency_id:
                payment = 0.0
            elif periodic_rate:
                payment = financed * periodic_rate / (1 - (1 + periodic_rate) ** -contract.installment_count)
            else:
                payment = financed / contract.installment_count
            contract.installment_amount = contract.currency_id.round(payment) if contract.currency_id else payment
            contract.total_interest = max(contract.currency_id.round(payment * contract.installment_count - financed), 0.0) if contract.currency_id else 0.0

    @api.depends("interest_rate", "frequency")
    def _compute_interest_method(self):
        labels = {"monthly": "mensuales", "bimonthly": "bimestrales", "quarterly": "trimestrales", "yearly": "anuales"}
        for contract in self:
            if contract.interest_rate:
                contract.interest_method = _("Amortización francesa (%s%% anual sobre saldo insoluto), cuotas %s") % (
                    f"{contract.interest_rate:.4f}", labels.get(contract.frequency, "mensuales"),
                )
            else:
                contract.interest_method = _("Sin interés (0 %)")

    @api.depends("installment_ids", "installment_ids.state", "installment_ids.amount_paid", "installment_ids.balance",
                 "installment_ids.due_date", "installment_ids.invoice_id.amount_total", "installment_ids.invoice_id.amount_residual",
                 "installment_ids.invoice_id.payment_state", "installment_ids.invoice_id.matched_payment_ids.date")
    def _compute_progress(self):
        for contract in self:
            lines = contract.installment_ids
            contract.total_installments = len(lines)
            contract.paid_installments = len(lines.filtered(lambda line: line.state == "paid"))
            contract.pending_installments = len(lines.filtered(lambda line: line.state in ("scheduled", "draft", "pending")))
            contract.overdue_installments = len(lines.filtered(lambda line: line.state == "overdue"))
            contract.partial_installments = len(lines.filtered(lambda line: line.state == "partial"))
            contract.draft_installments = len(lines.filtered(lambda line: line.state == "draft"))
            # Kabay contract readers may see these summaries without Accounting ACLs.
            invoices = lines.mapped("invoice_id").sudo().filtered(lambda move: move.state == "posted")
            contract.total_paid = sum(max(move.amount_total - move.amount_residual, 0.0) for move in invoices)
            contract.account_residual = sum(move.amount_residual for move in invoices)
            contract.scheduled_principal = sum(
                line.capital_amount + line.interest_amount for line in lines if not line.invoice_id and line.state != "cancelled"
            )
            outstanding = lines.filtered(lambda line: line.state in ("scheduled", "draft", "pending", "partial", "overdue"))
            contract.next_due_date = min(outstanding.mapped("due_date"), default=False)
            contract.progress_label = _("%s / %s") % (contract.paid_installments, contract.installment_count)

    @api.constrains("condominium_id", "apartment_id", "company_id", "currency_id", "buyer_id", "creditor_id")
    def _check_parties_and_scope(self):
        for contract in self:
            if contract.apartment_id.condominium_id != contract.condominium_id:
                raise ValidationError(_("El apartamento debe pertenecer al condominio del contrato."))
            if contract.apartment_id.company_id and contract.company_id != contract.apartment_id.company_id:
                raise ValidationError(_("La empresa facturadora debe coincidir con la empresa asignada al condominio/apartamento."))
            if contract.currency_id != contract.company_id.currency_id:
                raise ValidationError(_("La moneda del contrato debe coincidir con la moneda de la empresa facturadora."))
            for partner in (contract.buyer_id, contract.creditor_id):
                if partner.company_id and partner.company_id != contract.company_id:
                    raise ValidationError(_("Comprador y acreedor deben ser contactos globales o de la empresa facturadora."))

    @api.constrains("purchase_price", "down_payment", "installment_count", "due_day", "invoice_lead_days", "interest_rate", "grace_days")
    def _check_financial_values(self):
        for contract in self:
            if contract.purchase_price <= 0 or contract.down_payment < 0 or contract.down_payment >= contract.purchase_price:
                raise ValidationError(_("El precio debe ser positivo y la inicial debe ser menor que el precio total."))
            if contract.installment_count <= 0:
                raise ValidationError(_("El número de cuotas debe ser mayor que cero."))
            if contract.due_day and not 1 <= contract.due_day <= 31:
                raise ValidationError(_("El día de vencimiento debe estar entre 1 y 31."))
            if contract.invoice_lead_days < 0:
                raise ValidationError(_("Los días previos para generar facturas no pueden ser negativos."))
            if contract.interest_rate < 0:
                raise ValidationError(_("La tasa de interés no puede ser negativa."))
            if contract.grace_days < 0 or contract.grace_days > 60:
                raise ValidationError(_("Los días de gracia deben estar entre 0 y 60."))

    def write(self, vals):
        if "state" in vals:
            raise UserError(_("El estado del contrato solo cambia mediante sus acciones autorizadas."))
        financial_fields = {"condominium_id", "apartment_id", "buyer_id", "creditor_id", "company_id", "currency_id",
                            "product_id", "purchase_price", "down_payment", "installment_count", "frequency", "interest_rate",
                            "start_date", "due_day", "grace_days"}
        if financial_fields.intersection(vals) and any(contract.state != "draft" for contract in self):
            raise UserError(_("Los términos financieros quedan históricos al activar el contrato. Cree una modificación autorizada o un nuevo contrato."))
        return super().write(vals)

    def _transition_state(self, state):
        return super(KabayFinancingContract, self).write({"state": state})

    def action_confirm(self):
        if not self.env.is_system() and not self.env.user.has_group("kabay_base.group_kabay_manager"):
            raise AccessError(_("Solo Administración Kabay puede confirmar contratos y generar su calendario."))
        for contract in self:
            if contract.state != "draft":
                continue
            contract._check_financial_values()
            if not contract.company_id or not contract.company_id.currency_id:
                raise UserError(_("Configure una empresa y moneda facturadora válidas."))
            if contract.installment_ids:
                raise UserError(_("El borrador ya tiene cuotas; no se regenerará para evitar duplicados."))
            contract._generate_installment_schedule()
            contract._transition_state("active")
        return True

    def _generate_installment_schedule(self):
        for contract in self:
            count = contract.installment_count
            currency = contract.currency_id
            periods_per_year = {"monthly": 12, "bimonthly": 6, "quarterly": 4, "yearly": 1}[contract.frequency]
            periodic_rate = contract.interest_rate / 100.0 / periods_per_year
            if periodic_rate:
                payment = currency.round(contract.financed_amount * periodic_rate / (1 - (1 + periodic_rate) ** -count))
            else:
                payment = currency.round(contract.financed_amount / count)
            allocated = 0.0
            balance = contract.financed_amount
            due_day = contract.due_day or contract.start_date.day
            interval = {"monthly": 1, "bimonthly": 2, "quarterly": 3, "yearly": 12}[contract.frequency]
            vals_list = []
            for number in range(1, count + 1):
                month_index = contract.start_date.year * 12 + contract.start_date.month - 1 + (number - 1) * interval
                year, month_zero = divmod(month_index, 12)
                month = month_zero + 1
                day = min(due_day, monthrange(year, month)[1])
                interest = currency.round(balance * periodic_rate)
                capital = currency.round(contract.financed_amount - allocated) if number == count else min(currency.round(payment - interest), currency.round(contract.financed_amount - allocated))
                allocated += capital
                balance = max(currency.round(balance - capital), 0.0)
                vals_list.append({
                    "contract_id": contract.id,
                    "number": number,
                    "due_date": date(year, month, day),
                    "capital_amount": capital,
                    "interest_amount": interest,
                })
            self.env["kabay.financing.installment"]._create_schedule_lines(vals_list)

    def action_generate_invoices(self):
        self._check_finance_access()
        count = 0
        today = fields.Date.context_today(self)
        for contract in self:
            if contract.state != "active":
                raise UserError(_("Solo los contratos activos pueden generar facturas."))
            cutoff = today + timedelta(days=contract.invoice_lead_days)
            due_lines = contract.installment_ids.filtered(
                lambda line: line.state == "scheduled" and line.due_date <= cutoff and not line.invoice_id
            )
            count += len(due_lines._create_draft_invoices())
        return self._notification(_("Facturas borrador generadas: %s") % count)

    def action_suspend(self):
        self._check_manager_or_finance_access()
        self.filtered(lambda c: c.state == "active")._transition_state("suspended")
        return True

    def action_resume(self):
        self._check_manager_or_finance_access()
        self.filtered(lambda c: c.state == "suspended")._transition_state("active")
        return True

    def action_cancel(self):
        self._check_manager_or_finance_access()
        self.filtered(lambda c: c.state in ("draft", "active", "suspended"))._transition_state("cancelled")
        return True

    def action_view_early_settlement(self):
        self.ensure_one()
        amount = sum(self.installment_ids.mapped("balance"))
        return self._notification(_("Estimación informativa basada en facturas y cuotas aún programadas: %s %s. No registra liquidación ni pago.") % (self.currency_id.name, self.currency_id.round(amount)))

    def action_view_advance_credits(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Créditos contables disponibles de %s") % self.buyer_id.display_name,
            "res_model": "account.move.line",
            "view_mode": "list,form",
            "domain": [
                ("partner_id", "=", self.buyer_id.id), ("company_id", "=", self.company_id.id),
                ("account_id.account_type", "=", "asset_receivable"), ("reconciled", "=", False),
                ("amount_residual", "<", 0),
            ],
        }

    @api.model
    def _notification(self, message):
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {"title": _("Financiamiento"), "message": message, "type": "success", "sticky": False}}

    def _check_finance_access(self):
        if not self.env.user.has_group("kabay_base.group_kabay_finance") and not self.env.is_system():
            raise UserError(_("Solo Finanzas puede generar facturas de financiamiento."))

    def _check_manager_or_finance_access(self):
        user = self.env.user
        if not (user.has_group("kabay_base.group_kabay_manager") or user.has_group("kabay_base.group_kabay_finance") or self.env.is_system()):
            raise UserError(_("No tiene permisos para modificar el estado del contrato."))


class KabayFinancingInstallment(models.Model):
    _name = "kabay.financing.installment"
    _description = "Cuota de contrato financiado"
    _order = "contract_id, number"
    _check_company_auto = True

    contract_id = fields.Many2one("kabay.financing.contract", required=True, ondelete="restrict", index=True, check_company=True, string="Contrato de financiamiento")
    company_id = fields.Many2one(related="contract_id.company_id", store=True, index=True, string="Compañía")
    condominium_id = fields.Many2one(related="contract_id.condominium_id", store=True, index=True, string="Condominio")
    apartment_id = fields.Many2one(related="contract_id.apartment_id", store=True, index=True, string="Apartamento")
    buyer_id = fields.Many2one(related="contract_id.buyer_id", store=True, index=True, string="Comprador")
    currency_id = fields.Many2one(related="contract_id.currency_id", store=True, string="Moneda")
    number = fields.Integer(required=True, index=True, string="Número")
    due_date = fields.Date(required=True, index=True, string="Fecha de vencimiento")
    grace_end_date = fields.Date(compute="_compute_grace_end_date", compute_sudo=False, store=True, string="Fin del período de gracia")
    capital_amount = fields.Monetary(required=True, currency_field="currency_id", string="Capital")
    interest_amount = fields.Monetary(required=True, currency_field="currency_id", default=0.0, string="Interés")
    amount_total = fields.Monetary(compute="_compute_total", store=True, compute_sudo=False, currency_field="currency_id", string="Importe total")
    invoice_id = fields.Many2one("account.move", string="Factura", copy=False, ondelete="restrict", index=True, check_company=True)
    invoice_number = fields.Char(compute="_compute_payment_tracking", string="Número de factura")
    amount_paid = fields.Monetary(compute="_compute_amounts", compute_sudo=False, currency_field="currency_id", string="Abonado según Contabilidad")
    balance = fields.Monetary(compute="_compute_amounts", compute_sudo=False, currency_field="currency_id", string="Saldo según Contabilidad / calendario")
    payment_date = fields.Date(compute="_compute_payment_tracking", string="Fecha del último pago conciliado")
    payment_timing = fields.Selection([
        ("scheduled", "Aún no facturada"), ("draft", "Factura en borrador"),
        ("before_due", "Pendiente, antes del vencimiento"), ("grace", "Dentro de los días de gracia"),
        ("in_mora", "En mora"), ("paid_on_time", "Pagada a tiempo"),
        ("paid_grace", "Pagada durante la gracia"), ("paid_late", "Pagada con atraso"),
        ("paid_date_unknown", "Pagada; fecha no disponible"),
        ("partial", "Pago parcial"), ("partial_late", "Pago parcial en mora"),
    ], compute="_compute_payment_tracking", string="Situación del pago")
    days_in_arrears = fields.Integer(compute="_compute_payment_tracking", string="Días en mora")
    balance_in_arrears = fields.Monetary(compute="_compute_payment_tracking", currency_field="currency_id", string="Saldo en mora")
    state = fields.Selection([
        ("scheduled", "Programada"), ("draft", "Factura en borrador"), ("pending", "Pendiente"),
        ("partial", "Parcialmente pagada"), ("paid", "Pagada"), ("overdue", "Vencida"), ("cancelled", "Cancelada"),
    ], compute="_compute_amounts", compute_sudo=False, search="_search_state", string="Estado")

    _number_uniq = models.Constraint("unique(contract_id, number)", "El número de cuota debe ser único dentro del contrato.")
    _invoice_uniq = models.Constraint("unique(invoice_id)", "Una factura solo puede pertenecer a una cuota de financiamiento.")

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(_("Las cuotas solo se crean mediante la confirmación autorizada del contrato."))

    @api.model
    def _create_schedule_lines(self, vals_list):
        if not self.env.is_system() and not self.env.user.has_group("kabay_base.group_kabay_manager"):
            raise AccessError(_("Solo Administración Kabay puede generar calendarios de cuotas."))
        return super(KabayFinancingInstallment, self).create(vals_list)

    @api.depends("capital_amount", "interest_amount")
    def _compute_total(self):
        for line in self:
            line.amount_total = line.capital_amount + line.interest_amount

    @api.depends("due_date", "contract_id.grace_days")
    def _compute_grace_end_date(self):
        for line in self:
            line.grace_end_date = line.due_date + timedelta(days=line.contract_id.grace_days) if line.due_date else False

    @api.depends("invoice_id.state", "invoice_id.payment_state", "invoice_id.amount_total",
                 "invoice_id.amount_residual", "due_date", "contract_id.state", "contract_id.grace_days")
    def _compute_amounts(self):
        today = fields.Date.context_today(self)
        for line in self:
            # Keep Accounting access inside this derived Kabay summary only.
            invoice = line.invoice_id.sudo()
            line.amount_paid = max(invoice.amount_total - invoice.amount_residual, 0.0) if invoice and invoice.state == "posted" else 0.0
            if not invoice:
                line.balance = line.amount_total
            elif invoice.state == "cancel":
                line.balance = 0.0
            elif invoice.state == "draft":
                line.balance = invoice.amount_total
            else:
                line.balance = invoice.amount_residual
            if invoice and invoice.state == "cancel":
                line.state = "cancelled"
            elif invoice and invoice.state == "draft":
                line.state = "draft"
            elif invoice and invoice.state == "posted":
                if invoice.payment_state == "paid":
                    line.state = "paid"
                elif today > (line.due_date + timedelta(days=line.contract_id.grace_days)) and invoice.amount_residual > 0:
                    line.state = "overdue"
                elif invoice.payment_state in ("partial", "in_payment") or (invoice.amount_residual > 0 and invoice.amount_residual < invoice.amount_total):
                    line.state = "partial"
                else:
                    line.state = "pending"
            elif line.contract_id.state == "cancelled":
                line.state = "cancelled"
            else:
                line.state = "scheduled"

    @api.depends("due_date", "contract_id.grace_days", "invoice_id.state", "invoice_id.name",
                 "invoice_id.amount_residual", "invoice_id.payment_state", "invoice_id.matched_payment_ids.date")
    def _compute_payment_tracking(self):
        today = fields.Date.context_today(self)
        for line in self:
            grace_end = line.due_date + timedelta(days=line.contract_id.grace_days) if line.due_date else False
            invoice = line.invoice_id.sudo()
            if not invoice:
                line.invoice_number = _("No emitida")
            elif invoice.state == "posted" and invoice.name != "/":
                line.invoice_number = invoice.name
            else:
                line.invoice_number = _("Pendiente de publicar")
            payment_dates = invoice.matched_payment_ids.mapped("date") if invoice else []
            payment_date = max(payment_dates, default=False)
            line.payment_date = payment_date
            is_paid = bool(invoice and invoice.state == "posted" and invoice.payment_state == "paid")
            residual = invoice.amount_residual if invoice and invoice.state == "posted" else 0.0
            if not invoice:
                line.payment_timing = "scheduled"
            elif invoice.state == "draft":
                line.payment_timing = "draft"
            elif is_paid:
                if not payment_date:
                    line.payment_timing = "paid_date_unknown"
                elif payment_date <= line.due_date:
                    line.payment_timing = "paid_on_time"
                elif payment_date <= grace_end:
                    line.payment_timing = "paid_grace"
                else:
                    line.payment_timing = "paid_late"
            elif invoice.payment_state in ("partial", "in_payment"):
                line.payment_timing = "partial_late" if today > grace_end else "partial"
            elif today <= line.due_date:
                line.payment_timing = "before_due"
            elif today <= grace_end:
                line.payment_timing = "grace"
            else:
                line.payment_timing = "in_mora"
            reference_date = payment_date if is_paid else today
            line.days_in_arrears = max((reference_date - grace_end).days, 0) if grace_end and reference_date else 0
            line.balance_in_arrears = residual if residual > 0 and today > grace_end else 0.0

    @api.model
    def _search_state(self, operator, value):
        allowed_operators = {"=", "!=", "in", "not in"}
        allowed_states = set(dict(self._fields["state"].selection))
        requested_states = value if operator in ("in", "not in") else [value]
        if operator not in allowed_operators or not set(requested_states).issubset(allowed_states):
            raise ValueError(_("Filtro de estado no compatible."))
        today = fields.Date.context_today(self)
        domains = {
            "scheduled": [("invoice_id", "=", False), ("contract_id.state", "!=", "cancelled")],
            "draft": [("invoice_id.state", "=", "draft")],
            "pending": [("invoice_id.state", "=", "posted"), ("invoice_id.payment_state", "not in", ["paid", "partial", "in_payment"]), ("invoice_id.amount_residual", ">", 0)],
            "partial": [("invoice_id.state", "=", "posted"), ("invoice_id.payment_state", "in", ["partial", "in_payment"])],
            "paid": [("invoice_id.state", "=", "posted"), ("invoice_id.payment_state", "=", "paid")],
            "overdue": [("invoice_id.state", "=", "posted"), ("invoice_id.amount_residual", ">", 0)],
            "cancelled": ["|", ("invoice_id.state", "=", "cancel"), "&", ("invoice_id", "=", False), ("contract_id.state", "=", "cancelled")],
        }
        candidate_domains = [domains[state] for state in requested_states]
        if len(candidate_domains) == 1:
            candidate_domain = candidate_domains[0]
        else:
            candidate_domain = []
            for domain in candidate_domains[:-1]:
                candidate_domain.extend(["|"] + domain)
            candidate_domain.extend(candidate_domains[-1])
        candidates = self.search(candidate_domain)
        if requested_states and set(requested_states) <= {"pending", "partial", "paid", "overdue"}:
            candidates = candidates.filtered(lambda line: line.state in requested_states)
        elif "overdue" in requested_states or "pending" in requested_states or "partial" in requested_states:
            candidates = candidates.filtered(lambda line: line.state in requested_states)
        matching_ids = candidates.ids
        return [("id", "not in" if operator in ("!=", "not in") else "in", matching_ids)]

    @api.constrains("number", "capital_amount", "interest_amount", "due_date", "contract_id")
    def _check_installment(self):
        for line in self:
            if line.number <= 0 or line.capital_amount < 0 or line.interest_amount < 0:
                raise ValidationError(_("La cuota debe tener número positivo y capital/interés no negativos."))
            if line.interest_amount and not line.contract_id.interest_rate:
                raise ValidationError(_("No se pueden añadir intereses cuando el contrato tiene tasa 0 %."))

    def write(self, vals):
        if set(vals) != {"invoice_id"} or not self.env.context.get("kabay_financing_link_invoice"):
            raise UserError(_("El calendario y los importes de una cuota son históricos y no se editan directamente."))
        if not self.env.user.has_group("kabay_base.group_kabay_finance"):
            raise UserError(_("Solo Finanzas puede enlazar una factura generada a una cuota."))
        invoice = self.env["account.move"].browse(vals.get("invoice_id")).exists()
        if not invoice:
            raise UserError(_("Seleccione una factura de financiamiento existente."))
        for line in self:
            if line.invoice_id or line.contract_id.state != "active":
                raise UserError(_("Solo se puede enlazar una factura a una cuota activa sin factura previa."))
            line._check_invoice_identity(invoice)
        return super().write(vals)

    def _check_invoice_identity(self, invoice):
        self.ensure_one()
        invoice.ensure_one()
        if any((
            invoice.state != "draft",
            invoice.move_type != "out_invoice",
            invoice.company_id != self.company_id,
            invoice.currency_id != self.currency_id,
            invoice.partner_id != self.buyer_id,
            invoice.kabay_financing_contract_id != self.contract_id,
            invoice.kabay_financing_installment_id != self,
            invoice.kabay_financing_apartment_id != self.apartment_id,
            invoice.kabay_financing_creditor_id != self.contract_id.creditor_id,
        )):
            raise ValidationError(_("La factura borrador debe corresponder a esta cuota, comprador, empresa y moneda."))
        return True

    def _create_draft_invoices(self):
        created = self.env["account.move"]
        for line in self:
            if line.invoice_id:
                continue
            contract = line.contract_id
            if contract.state != "active":
                continue
            company = contract.company_id
            product = contract.product_id.with_company(company)
            journal = self.env["account.journal"].search([("company_id", "=", company.id), ("type", "=", "sale")], limit=1)
            income_account = product.property_account_income_id or product.categ_id.property_account_income_categ_id
            if not journal or not income_account:
                raise UserError(_("Configure un diario de ventas y una cuenta de ingresos para el producto %s.") % product.display_name)
            existing = self.env["account.move"].search([("kabay_financing_installment_id", "=", line.id)], limit=1)
            if existing:
                line.with_context(kabay_financing_link_invoice=True).write({"invoice_id": existing.id})
                continue
            taxes = product.taxes_id.filtered(lambda tax: tax.company_id == company)
            label = _("Contrato %s — cuota %s/%s") % (contract.name, line.number, contract.installment_count)
            move = self.env["account.move"].with_company(company).create({
                "move_type": "out_invoice",
                "company_id": company.id,
                "journal_id": journal.id,
                "partner_id": contract.buyer_id.id,
                "invoice_date": fields.Date.context_today(self),
                "invoice_date_due": line.due_date,
                "invoice_payment_term_id": False,
                "currency_id": contract.currency_id.id,
                "kabay_financing_contract_id": contract.id,
                "kabay_financing_installment_id": line.id,
                "kabay_financing_apartment_id": contract.apartment_id.id,
                "kabay_financing_creditor_id": contract.creditor_id.id,
                "invoice_line_ids": [Command.create({
                    "name": label,
                    "product_id": product.id,
                    "quantity": 1.0,
                    "price_unit": line.amount_total,
                    "account_id": income_account.id,
                    "tax_ids": [Command.set(taxes.ids)],
                    "kabay_financing_installment_id": line.id,
                })],
            })
            line.with_context(kabay_financing_link_invoice=True).write({"invoice_id": move.id})
            created |= move
        return created

    def action_generate_invoice(self):
        self.contract_id._check_finance_access()
        created = self._create_draft_invoices()
        if not created:
            raise UserError(_("No hay una cuota facturable nueva."))
        return {
            "type": "ir.actions.act_window", "name": _("Factura borrador"), "res_model": "account.move",
            "res_id": created[:1].id, "view_mode": "form", "target": "current",
        }

    def action_validate_payment_group(self):
        self.contract_id._check_finance_access()
        if not self:
            raise UserError(_("Seleccione al menos una cuota."))
        checks = {
            "contract_id": self.mapped("contract_id"),
            "buyer_id": self.mapped("buyer_id"),
            "company_id": self.mapped("company_id"),
            "currency_id": self.mapped("currency_id"),
        }
        if any(len(records) != 1 for records in checks.values()):
            raise UserError(_("Las cuotas deben pertenecer al mismo contrato, comprador, empresa y moneda."))
        if any(not line.invoice_id or line.invoice_id.state != "posted" for line in self):
            raise UserError(_("Solo puede agrupar cuotas con facturas publicadas en Contabilidad."))
        total_residual = sum(self.mapped("invoice_id.amount_residual"))
        return self.env["kabay.financing.contract"]._notification(
            _("Selección válida: %s facturas, saldo contable %s %s. Este control no registra pagos.")
            % (len(self), self.currency_id.name, self.currency_id.round(total_residual))
        )


class AccountMove(models.Model):
    _inherit = "account.move"

    kabay_financing_contract_id = fields.Many2one("kabay.financing.contract", copy=False, ondelete="restrict", index=True, check_company=True, string="Contrato de financiamiento")
    kabay_financing_installment_id = fields.Many2one("kabay.financing.installment", copy=False, ondelete="restrict", index=True, check_company=True, string="Cuota de financiamiento")
    kabay_financing_apartment_id = fields.Many2one("kabay.apartment", copy=False, ondelete="restrict", index=True, check_company=True, string="Apartamento financiado")
    kabay_financing_creditor_id = fields.Many2one("res.partner", copy=False, ondelete="restrict", index=True, check_company=True, string="Acreedor del financiamiento")
    _kabay_financing_installment_uniq = models.Constraint(
        "unique(kabay_financing_installment_id)", "Una cuota solo puede tener una factura de financiamiento."
    )

    @api.constrains(
        "move_type", "state", "company_id", "currency_id", "partner_id",
        "kabay_financing_contract_id", "kabay_financing_installment_id",
        "kabay_financing_apartment_id", "kabay_financing_creditor_id",
    )
    def _check_kabay_financing_invoice(self):
        for move in self:
            installment = move.kabay_financing_installment_id
            contract = move.kabay_financing_contract_id
            if not (installment or contract or move.kabay_financing_apartment_id or move.kabay_financing_creditor_id):
                continue
            if not installment or not contract or installment.contract_id != contract:
                raise ValidationError(_("La factura de financiamiento debe estar vinculada a su contrato y cuota."))
            if (
                move.move_type != "out_invoice"
                or move.company_id != contract.company_id
                or move.currency_id != contract.currency_id
                or move.partner_id != contract.buyer_id
                or move.kabay_financing_apartment_id != contract.apartment_id
                or move.kabay_financing_creditor_id != contract.creditor_id
            ):
                raise ValidationError(_("La factura de financiamiento debe conservar comprador, unidad, empresa y moneda del contrato."))

    def write(self, vals):
        financing_fields = {
            "kabay_financing_contract_id", "kabay_financing_installment_id",
            "kabay_financing_apartment_id", "kabay_financing_creditor_id",
        }
        if financing_fields.intersection(vals) and any(move.state == "posted" for move in self):
            raise UserError(_("La identidad de una factura de financiamiento publicada es histórica."))
        return super().write(vals)


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    kabay_financing_installment_id = fields.Many2one("kabay.financing.installment", copy=False, ondelete="restrict", index=True, check_company=True, string="Cuota de financiamiento")

    @api.constrains("move_id", "kabay_financing_installment_id")
    def _check_kabay_financing_line_identity(self):
        for line in self:
            installment = line.kabay_financing_installment_id
            if installment and (
                line.move_id.kabay_financing_installment_id != installment
                or line.move_id.kabay_financing_contract_id != installment.contract_id
                or line.move_id.company_id != installment.company_id
            ):
                raise ValidationError(_("La línea contable debe conservar el contrato, cuota y compañía Kabay."))

    def write(self, vals):
        if "kabay_financing_installment_id" in vals and any(line.move_id.state == "posted" for line in self):
            raise UserError(_("La asignación de cuota de una línea publicada es histórica."))
        return super().write(vals)
