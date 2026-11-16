from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


FINANCE_GROUPS = "kabay_base.group_kabay_manager,kabay_base.group_kabay_finance"


class KabayReportDashboard(models.TransientModel):
    _name = "kabay.report.dashboard"
    _description = "Panel de indicadores Kabay"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, string="Compañía")
    condominium_id = fields.Many2one("kabay.condominium", domain="[('company_id', '=', company_id)]", string="Condominio")
    building_id = fields.Many2one("kabay.building", domain="[('condominium_id', '=', condominium_id)]", string="Edificio / torre")
    apartment_id = fields.Many2one("kabay.apartment", domain="[('building_id', '=', building_id)]", string="Apartamento")
    date_from = fields.Date(string="Fecha desde")
    date_to = fields.Date(default=fields.Date.context_today, string="Fecha hasta")

    condominium_count = fields.Integer(compute="_compute_metrics", string="Cantidad de condominios")
    building_count = fields.Integer(compute="_compute_metrics", string="Cantidad de edificios")
    apartment_count = fields.Integer(compute="_compute_metrics", string="Cantidad de apartamentos")
    occupied_count = fields.Integer(compute="_compute_metrics", string="Unidades ocupadas")
    without_current_relation_count = fields.Integer(compute="_compute_metrics", string="Sin relación vigente")
    owner_count = fields.Integer(compute="_compute_metrics", string="Cantidad de propietarios")
    tenant_count = fields.Integer(compute="_compute_metrics", string="Cantidad de inquilinos")
    authorized_resident_count = fields.Integer(compute="_compute_metrics", string="Residentes autorizados")

    currency_id = fields.Many2one(related="company_id.currency_id", string="Moneda")
    invoiced_total = fields.Monetary(compute="_compute_metrics", currency_field="currency_id", groups=FINANCE_GROUPS, string="Total facturado")
    collected_total = fields.Monetary(compute="_compute_metrics", currency_field="currency_id", groups=FINANCE_GROUPS, string="Total cobrado")
    receivable_total = fields.Monetary(compute="_compute_metrics", currency_field="currency_id", groups=FINANCE_GROUPS, string="Cuentas por cobrar")
    overdue_total = fields.Monetary(compute="_compute_metrics", currency_field="currency_id", groups=FINANCE_GROUPS, string="Total vencido")
    receivable_1_30 = fields.Monetary(compute="_compute_metrics", currency_field="currency_id", groups=FINANCE_GROUPS, string="Vencido 1–30 días")
    receivable_31_60 = fields.Monetary(compute="_compute_metrics", currency_field="currency_id", groups=FINANCE_GROUPS, string="Vencido 31–60 días")
    receivable_61_90 = fields.Monetary(compute="_compute_metrics", currency_field="currency_id", groups=FINANCE_GROUPS, string="Vencido 61–90 días")
    receivable_over_90 = fields.Monetary(compute="_compute_metrics", currency_field="currency_id", groups=FINANCE_GROUPS, string="Vencido más de 90 días")
    open_invoice_count = fields.Integer(compute="_compute_metrics", groups=FINANCE_GROUPS, string="Facturas abiertas")
    overdue_invoice_count = fields.Integer(compute="_compute_metrics", groups=FINANCE_GROUPS, string="Facturas vencidas")
    paid_invoice_count = fields.Integer(compute="_compute_metrics", groups=FINANCE_GROUPS, string="Facturas pagadas")
    credit_note_total = fields.Monetary(compute="_compute_metrics", currency_field="currency_id", groups=FINANCE_GROUPS, string="Total de notas de crédito")
    reconciled_payment_count = fields.Integer(compute="_compute_metrics", groups=FINANCE_GROUPS, string="Pagos conciliados")

    active_contract_count = fields.Integer(compute="_compute_metrics", groups=FINANCE_GROUPS, string="Contratos activos")
    financed_total = fields.Monetary(compute="_compute_metrics", currency_field="currency_id", groups=FINANCE_GROUPS, string="Total financiado")
    capital_pending_total = fields.Monetary(compute="_compute_metrics", currency_field="currency_id", groups=FINANCE_GROUPS, string="Capital pendiente")
    installment_count = fields.Integer(compute="_compute_metrics", groups=FINANCE_GROUPS, string="Cantidad de cuotas")
    paid_installment_count = fields.Integer(compute="_compute_metrics", groups=FINANCE_GROUPS, string="Cuotas pagadas")
    overdue_installment_count = fields.Integer(compute="_compute_metrics", groups=FINANCE_GROUPS, string="Cuotas vencidas")

    open_ticket_count = fields.Integer(compute="_compute_metrics", groups="kabay_base.group_kabay_manager,kabay_base.group_kabay_management,kabay_base.group_kabay_reception,kabay_base.group_kabay_maintenance", string="Solicitudes abiertas")
    in_progress_ticket_count = fields.Integer(compute="_compute_metrics", groups="kabay_base.group_kabay_manager,kabay_base.group_kabay_management,kabay_base.group_kabay_reception,kabay_base.group_kabay_maintenance", string="Solicitudes en curso")
    resolved_ticket_count = fields.Integer(compute="_compute_metrics", groups="kabay_base.group_kabay_manager,kabay_base.group_kabay_management,kabay_base.group_kabay_reception,kabay_base.group_kabay_maintenance", string="Solicitudes resueltas")
    cancelled_ticket_count = fields.Integer(compute="_compute_metrics", groups="kabay_base.group_kabay_manager,kabay_base.group_kabay_management,kabay_base.group_kabay_reception,kabay_base.group_kabay_maintenance", string="Solicitudes canceladas")
    published_notice_count = fields.Integer(compute="_compute_metrics", string="Avisos publicados")
    pending_notice_count = fields.Integer(compute="_compute_metrics", string="Avisos pendientes")

    @api.constrains("date_from", "date_to")
    def _check_date_range(self):
        if any(rec.date_from and rec.date_to and rec.date_from > rec.date_to for rec in self):
            raise ValidationError(_("La fecha inicial no puede ser posterior a la final."))

    @api.depends("company_id", "condominium_id", "building_id", "apartment_id", "date_from", "date_to")
    def _compute_metrics(self):
        today = fields.Date.context_today(self)
        for panel in self:
            panel._clear_metrics()
            if not panel.company_id or panel.company_id not in self.env.companies:
                continue
            if panel.condominium_id and panel.condominium_id.company_id != panel.company_id:
                continue
            if panel.building_id and (not panel.condominium_id or panel.building_id.condominium_id != panel.condominium_id):
                continue
            if panel.apartment_id and (not panel.building_id or panel.apartment_id.building_id != panel.building_id):
                continue
            company_domain = [("company_id", "=", panel.company_id.id)]
            if panel.condominium_id:
                company_domain.append(("id", "=", panel.condominium_id.id))
            condos = self.env["kabay.condominium"].search(company_domain)
            building_domain = [("condominium_id", "in", condos.ids)]
            if panel.building_id:
                building_domain.append(("id", "=", panel.building_id.id))
            buildings = self.env["kabay.building"].search(building_domain)
            apartment_domain = [("building_id", "in", buildings.ids), ("active", "=", True)]
            if panel.apartment_id:
                apartment_domain.append(("id", "=", panel.apartment_id.id))
            apartments = self.env["kabay.apartment"].search(apartment_domain)
            rel_domain = [
                ("apartment_id", "in", apartments.ids), ("state", "=", "confirmed"),
                ("active", "=", True), ("date_start", "<=", today),
                "|", ("date_end", "=", False), ("date_end", ">=", today),
            ]
            relations = self.env["kabay.apartment.relation"].search(rel_domain)
            occupied_ids = set(relations.mapped("apartment_id").ids)
            panel.condominium_count = len(condos)
            panel.building_count = len(buildings)
            panel.apartment_count = len(apartments)
            panel.occupied_count = len(occupied_ids)
            panel.without_current_relation_count = max(len(apartments) - len(occupied_ids), 0)
            panel.owner_count = len(relations.filtered(lambda r: r.role == "owner").mapped("partner_id"))
            panel.tenant_count = len(relations.filtered(lambda r: r.role == "tenant").mapped("partner_id"))
            panel.authorized_resident_count = len(relations.filtered(lambda r: r.role == "authorized_resident").mapped("partner_id"))
            panel._compute_operations(company_domain, condos, buildings, apartments)
            if panel._has_finance_access():
                panel._compute_finance(company_domain, condos, apartments, today)

    def _clear_metrics(self):
        for name in (
            "condominium_count building_count apartment_count occupied_count without_current_relation_count owner_count tenant_count authorized_resident_count "
            "invoiced_total collected_total receivable_total overdue_total receivable_1_30 receivable_31_60 receivable_61_90 receivable_over_90 open_invoice_count overdue_invoice_count paid_invoice_count credit_note_total reconciled_payment_count "
            "active_contract_count financed_total capital_pending_total installment_count paid_installment_count overdue_installment_count "
            "open_ticket_count in_progress_ticket_count resolved_ticket_count cancelled_ticket_count published_notice_count pending_notice_count"
        ).split():
            self[name] = 0

    def _has_finance_access(self):
        has_business_group = (
            self.env.user.has_group("kabay_base.group_kabay_finance")
            or self.env.user.has_group("kabay_base.group_kabay_manager")
        )
        return has_business_group and all(
            self.env[model].check_access_rights("read", raise_exception=False)
            for model in ("account.move", "account.payment")
        )

    def _compute_finance(self, company_domain, condos, apartments, today):
        base = [("company_id", "=", self.company_id.id), ("state", "=", "posted")]
        if self.date_from:
            base.append(("invoice_date", ">=", self.date_from))
        if self.date_to:
            base.append(("invoice_date", "<=", self.date_to))
        scope = self._invoice_scope_domain(condos, apartments, include_condominium=not (self.building_id or self.apartment_id))
        moves = self.env["account.move"].search(base + scope + [("move_type", "=", "out_invoice")])
        credits = self.env["account.move"].search(base + scope + [("move_type", "=", "out_refund")])
        invoice_summary = self._summarize_invoices(moves, credits, today)
        for field_name, amount in invoice_summary.items():
            self[field_name] = amount
        payment_domain = [("company_id", "=", self.company_id.id), ("is_reconciled", "=", True)]
        invoice_ids = set(moves.ids)
        if invoice_ids:
            payment_domain.append(("reconciled_invoice_ids", "in", list(invoice_ids)))
        else:
            payment_domain.append(("id", "=", 0))
        if self.date_from:
            payment_domain.append(("date", ">=", self.date_from))
        if self.date_to:
            payment_domain.append(("date", "<=", self.date_to))
        payments = self.env["account.payment"].search(payment_domain)
        # Exclude mixed payments: their full amount cannot safely be attributed to Kabay.
        linked = payments.filtered(lambda p: self._payment_is_fully_attributable(p.reconciled_invoice_ids.ids, invoice_ids))
        self.collected_total = sum(
            payment.currency_id._convert(payment.amount, self.company_id.currency_id, self.company_id, payment.date)
            for payment in linked
        )
        self.reconciled_payment_count = len(linked)
        contracts = self.env["kabay.financing.contract"].search([
            ("company_id", "=", self.company_id.id), ("state", "=", "active"),
            ("apartment_id", "in", apartments.ids),
        ])
        self.active_contract_count = len(contracts)
        self.financed_total = sum(contracts.mapped("financed_amount"))
        self.capital_pending_total = sum(contracts.mapped("account_residual")) + sum(contracts.mapped("scheduled_principal"))
        installments = self.env["kabay.financing.installment"].search([
            ("company_id", "=", self.company_id.id), ("apartment_id", "in", apartments.ids),
            ("contract_id.state", "=", "active"),
        ])
        installment_summary = self._summarize_installments(installments)
        self.installment_count = installment_summary["total"]
        self.paid_installment_count = installment_summary["paid"]
        self.overdue_installment_count = installment_summary["overdue"]

    def _compute_operations(self, company_domain, condos, buildings, apartments):
        Ticket = self.env["helpdesk.ticket"]
        if Ticket.check_access_rights("read", raise_exception=False):
            ticket_domain = [("company_id", "=", self.company_id.id), ("kabay_apartment_id", "!=", False)]
            if condos:
                ticket_domain.append(("kabay_condominium_id", "in", condos.ids))
            if self.building_id:
                ticket_domain.append(("kabay_building_id", "=", self.building_id.id))
            if self.apartment_id:
                ticket_domain.append(("kabay_apartment_id", "=", self.apartment_id.id))
            if self.date_from:
                ticket_domain.append(("create_date", ">=", fields.Datetime.to_datetime(self.date_from)))
            if self.date_to:
                ticket_domain.append(("create_date", "<=", fields.Datetime.to_datetime(self.date_to).replace(hour=23, minute=59, second=59)))
            tickets = Ticket.search(ticket_domain)
            ticket_summary = self._summarize_tickets(tickets)
            self.open_ticket_count = ticket_summary["open"]
            self.in_progress_ticket_count = ticket_summary["in_progress"]
            self.resolved_ticket_count = ticket_summary["resolved"]
            self.cancelled_ticket_count = ticket_summary["cancelled"]
        notices = self.env["kabay.notice"].search([("company_id", "=", self.company_id.id)])
        if self.apartment_id:
            apartment = self.apartment_id
            notices = notices.filtered(lambda n: (
                n.scope == "company"
                or (n.scope == "condominium" and n.condominium_id == apartment.condominium_id)
                or (n.scope == "building" and n.building_id == apartment.building_id)
                or (n.scope == "apartments" and apartment in n.apartment_ids)
            ))
        elif self.building_id:
            building = self.building_id
            notices = notices.filtered(lambda n: (
                n.scope == "company"
                or (n.scope == "condominium" and n.condominium_id == building.condominium_id)
                or (n.scope == "building" and n.building_id == building)
                or (n.scope == "apartments" and bool(n.apartment_ids & apartments))
            ))
        elif self.condominium_id:
            condominium = self.condominium_id
            notices = notices.filtered(lambda n: (
                n.scope == "company"
                or (n.scope == "condominium" and n.condominium_id == condominium)
                or (n.scope == "building" and n.building_id.condominium_id == condominium)
                or (n.scope == "apartments" and bool(n.apartment_ids & apartments))
            ))
        if self.date_from:
            notices = notices.filtered(lambda n: n.publish_datetime.date() >= self.date_from)
        if self.date_to:
            notices = notices.filtered(lambda n: n.publish_datetime.date() <= self.date_to)
        self.published_notice_count = len(notices.filtered(lambda n: n.state == "published"))
        self.pending_notice_count = len(notices.filtered(lambda n: n.state in ("draft", "scheduled", "publishing")))

    @api.model
    def _invoice_scope_domain(self, condos, apartments, include_condominium=True):
        apartment_terms = [
            ("kabay_apartment_id", "in", apartments.ids),
            ("kabay_financing_apartment_id", "in", apartments.ids),
        ]
        if include_condominium:
            return ["|", "|", ("kabay_condominium_id", "in", condos.ids), *apartment_terms]
        return ["|", *apartment_terms]

    @api.model
    def _receivable_age_bucket(self, due_date, as_of):
        if not due_date or due_date >= as_of:
            return False
        days_overdue = (as_of - due_date).days
        if days_overdue <= 30:
            return "receivable_1_30"
        if days_overdue <= 60:
            return "receivable_31_60"
        if days_overdue <= 90:
            return "receivable_61_90"
        return "receivable_over_90"

    @api.model
    def _summarize_invoices(self, invoices, credit_notes, as_of):
        posted_invoices = [m for m in invoices if m.state == "posted" and m.move_type == "out_invoice"]
        posted_credits = [m for m in credit_notes if m.state == "posted" and m.move_type == "out_refund"]
        pending = [m for m in posted_invoices if m.amount_residual_signed > 0]
        overdue = [m for m in pending if m.invoice_date_due and m.invoice_date_due < as_of]
        result = {
            "invoiced_total": sum(m.amount_total_signed for m in posted_invoices),
            "collected_total": 0.0,
            "receivable_total": sum(m.amount_residual_signed for m in pending),
            "overdue_total": sum(m.amount_residual_signed for m in overdue),
            "open_invoice_count": len(pending),
            "overdue_invoice_count": len(overdue),
            "paid_invoice_count": sum(1 for m in posted_invoices if m.payment_state == "paid"),
            "credit_note_total": sum(abs(m.amount_total_signed) for m in posted_credits),
            "receivable_1_30": 0.0,
            "receivable_31_60": 0.0,
            "receivable_61_90": 0.0,
            "receivable_over_90": 0.0,
        }
        for move in overdue:
            result[self._receivable_age_bucket(move.invoice_date_due, as_of)] += move.amount_residual_signed
        return result

    @api.model
    def _payment_is_fully_attributable(self, reconciled_invoice_ids, report_invoice_ids):
        payment_invoices = set(reconciled_invoice_ids)
        return bool(payment_invoices) and payment_invoices.issubset(set(report_invoice_ids))

    @api.model
    def _summarize_installments(self, installments):
        states = [line.state for line in installments]
        return {
            "total": len(states),
            "paid": sum(1 for state in states if state == "paid"),
            "overdue": sum(1 for state in states if state == "overdue"),
        }

    @api.model
    def _summarize_tickets(self, tickets):
        states = [ticket.kabay_state for ticket in tickets]
        return {
            "open": sum(1 for state in states if state in ("new", "review", "assigned", "waiting_resident")),
            "in_progress": states.count("in_progress"),
            "resolved": sum(1 for state in states if state in ("resolved", "closed")),
            "cancelled": states.count("cancelled"),
        }

    def action_open_invoices(self):
        self.ensure_one()
        if not self._has_finance_access():
            raise AccessError(_("No tiene permiso para consultar reportes financieros."))
        condos = self.env["kabay.condominium"].search([("company_id", "=", self.company_id.id)])
        apartments = self.env["kabay.apartment"].search([("company_id", "=", self.company_id.id)])
        scope = self._invoice_scope_domain(condos, apartments)
        if self.condominium_id:
            condos = self.condominium_id
            apartments = self.env["kabay.apartment"].search([("condominium_id", "=", self.condominium_id.id)])
            scope = self._invoice_scope_domain(condos, apartments)
        if self.building_id:
            apartments = self.env["kabay.apartment"].search([("building_id", "=", self.building_id.id)])
            scope = self._invoice_scope_domain(self.env["kabay.condominium"], apartments, include_condominium=False)
        if self.apartment_id:
            apartments = self.apartment_id
            scope = self._invoice_scope_domain(self.env["kabay.condominium"], apartments, include_condominium=False)
        domain = [("company_id", "=", self.company_id.id), ("state", "=", "posted"), ("move_type", "in", ["out_invoice", "out_refund"])] + scope
        if self.date_from:
            domain.append(("invoice_date", ">=", self.date_from))
        if self.date_to:
            domain.append(("invoice_date", "<=", self.date_to))
        return {"type": "ir.actions.act_window", "name": _("Facturación Kabay"), "res_model": "account.move", "view_mode": "list,form", "domain": domain, "context": {"search_default_group_by_kabay_condominium_id": 1}}

    def action_open_receivables(self):
        self.ensure_one()
        if not self._has_finance_access():
            raise AccessError(_("No tiene permiso para consultar cuentas por cobrar."))
        invoice_action = self.action_open_invoices()
        invoice_action.update({"name": _("Cuentas por cobrar Kabay"), "domain": invoice_action["domain"] + [("move_type", "=", "out_invoice"), ("amount_residual", ">", 0)]})
        return invoice_action

    def action_open_payments(self):
        self.ensure_one()
        if not self._has_finance_access():
            raise AccessError(_("No tiene permiso para consultar cobros."))
        invoice_action = self.action_open_invoices()
        invoice_ids = set(self.env["account.move"].search(invoice_action["domain"]).ids)
        payment_domain = [("company_id", "=", self.company_id.id), ("is_reconciled", "=", True), ("reconciled_invoice_ids", "in", invoice_ids)]
        if self.date_from:
            payment_domain.append(("date", ">=", self.date_from))
        if self.date_to:
            payment_domain.append(("date", "<=", self.date_to))
        candidates = self.env["account.payment"].search(payment_domain) if invoice_ids else self.env["account.payment"]
        payment_ids = candidates.filtered(lambda p: bool(p.reconciled_invoice_ids)
                                           and set(p.reconciled_invoice_ids.ids).issubset(invoice_ids)).ids
        return {"type": "ir.actions.act_window", "name": _("Cobros conciliados"), "res_model": "account.payment", "view_mode": "list,form", "domain": [("id", "in", payment_ids)]}
