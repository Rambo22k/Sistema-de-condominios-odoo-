from datetime import date, timedelta
from math import isclose

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class KabayApartmentRelation(models.Model):
    _name = "kabay.apartment.relation"
    _description = "Relación histórica entre persona y apartamento"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "apartment_id, date_start desc, id desc"

    partner_id = fields.Many2one(
        "res.partner", required=True, ondelete="restrict", index=True, tracking=True
    , string="Contacto")
    apartment_id = fields.Many2one(
        "kabay.apartment", required=True, ondelete="restrict", index=True, tracking=True
    , string="Apartamento")
    condominium_id = fields.Many2one(
        "kabay.condominium", related="apartment_id.condominium_id", store=True, index=True
    , string="Condominio")
    building_id = fields.Many2one(
        "kabay.building", related="apartment_id.building_id", store=True, index=True
    , string="Edificio / torre")
    role = fields.Selection(
        [
            ("owner", "Propietario"),
            ("tenant", "Inquilino"),
            ("authorized_resident", "Residente autorizado"),
        ],
        required=True,
        index=True,
        tracking=True, string="Rol residencial",
    )
    date_start = fields.Date(required=True, default=fields.Date.context_today, tracking=True, string="Fecha de inicio")
    date_end = fields.Date(tracking=True, string="Fecha de fin")
    ownership_share = fields.Float(string="Participación (%)", digits=(5, 2), tracking=True)
    state = fields.Selection(
        [("draft", "Borrador"), ("confirmed", "Confirmada"), ("ended", "Finalizada")],
        default="draft",
        required=True,
        tracking=True,
        index=True, string="Estado",
    )
    active = fields.Boolean(default=True, tracking=True, string="Activo")
    is_current = fields.Boolean(compute="_compute_is_current", string="Relación vigente")
    company_id = fields.Many2one(
        "res.company", related="apartment_id.company_id", store=True, index=True
    , string="Compañía")
    notes = fields.Text(string="Observaciones")

    _identity_date_start_uniq = models.Constraint(
        "unique(partner_id, apartment_id, role, date_start)",
        "Ya existe una relación con la misma persona, unidad, rol y fecha de inicio.",
    )

    @api.depends("state", "active", "date_start", "date_end")
    def _compute_is_current(self):
        today = fields.Date.context_today(self)
        for relation in self:
            relation.is_current = bool(
                relation.active
                and relation.state == "confirmed"
                and relation.date_start <= today
                and (not relation.date_end or relation.date_end >= today)
            )


    @api.model_create_multi
    def create(self, vals_list):
        self._lock_apartments(vals.get("apartment_id") for vals in vals_list)
        return super().create(vals_list)

    def write(self, vals):
        protected = {"partner_id", "apartment_id", "role", "date_start", "date_end", "ownership_share"}
        if protected.intersection(vals) and not self.env.context.get("kabay_allow_history_close"):
            if self.filtered(lambda relation: relation.state != "draft"):
                raise UserError(_("Una relación confirmada conserva sus datos históricos. Finalícela y cree otra relación."))
        apartment_ids = set(self.mapped("apartment_id").ids)
        if vals.get("apartment_id"):
            apartment_ids.add(vals["apartment_id"])
        self._lock_apartments(apartment_ids)
        return super().write(vals)

    def _lock_apartments(self, apartment_ids):
        ids = sorted({int(apartment_id) for apartment_id in apartment_ids if apartment_id})
        if ids:
            self.env.cr.execute(
                "SELECT id FROM kabay_apartment WHERE id = ANY(%s) ORDER BY id FOR UPDATE",
                [ids],
            )

    @api.constrains("partner_id", "apartment_id", "role", "date_start", "date_end")
    def _check_dates_and_overlap(self):
        for relation in self:
            if relation.date_end and relation.date_end < relation.date_start:
                raise ValidationError(_("La fecha final no puede ser anterior a la fecha inicial."))
            overlaps = self.with_context(active_test=False).search([
                ("id", "not in", relation.ids),
                ("partner_id", "=", relation.partner_id.id),
                ("apartment_id", "=", relation.apartment_id.id),
                ("role", "=", relation.role),
            ])
            for other in overlaps:
                starts_before_other_ends = not other.date_end or relation.date_start <= other.date_end
                other_starts_before_ends = not relation.date_end or other.date_start <= relation.date_end
                if starts_before_other_ends and other_starts_before_ends:
                    raise ValidationError(_(
                        "Esta persona ya tiene una relación del mismo rol con la unidad durante ese período."
                    ))

    @api.constrains("ownership_share")
    def _check_ownership_share(self):
        for relation in self:
            if relation.ownership_share and relation.role != "owner":
                raise ValidationError(_("Solo un propietario puede tener porcentaje de participación."))
            if relation.ownership_share and not 0 < relation.ownership_share <= 100:
                raise ValidationError(_("La participación debe estar entre 0 y 100 %."))

    @api.constrains("partner_id", "company_id")
    def _check_partner_company(self):
        for relation in self:
            if (
                relation.partner_id.company_id
                and relation.company_id
                and relation.partner_id.company_id != relation.company_id
            ):
                raise ValidationError(_(
                    "La compañía del contacto no coincide con la compañía de la unidad."
                ))

    def action_confirm(self):
        for relation in self:
            if relation.state != "draft":
                continue
            if not relation.active:
                raise UserError(_("Reactive la relación antes de confirmarla."))
            if relation.role == "owner":
                relation._check_owner_distribution()
            relation.write({"state": "confirmed"})
        return True

    def _check_owner_distribution(self):
        owners = self.search([
            ("apartment_id", "=", self.apartment_id.id),
            ("role", "=", "owner"),
            ("state", "in", ["draft", "confirmed"]),
            ("active", "=", True),
        ])
        owners = owners.filtered(lambda owner: self._periods_overlap(owner, self))
        boundaries = {self.date_start}
        for owner in owners:
            if owner.date_start >= self.date_start and (
                not self.date_end or owner.date_start <= self.date_end
            ):
                boundaries.add(owner.date_start)
            if owner.date_end and owner.date_end >= self.date_start:
                next_day = owner.date_end + timedelta(days=1)
                if not self.date_end or next_day <= self.date_end:
                    boundaries.add(next_day)
        for day in sorted(boundaries):
            current = owners.filtered(
                lambda owner: owner.date_start <= day and (not owner.date_end or owner.date_end >= day)
            )
            if not current or not any(owner.ownership_share for owner in current):
                continue
            if any(not owner.ownership_share for owner in current) or not isclose(
                sum(current.mapped("ownership_share")), 100.0, abs_tol=0.01
            ):
                raise ValidationError(_(
                    "Cuando se configura la participación de propietarios, cada período debe sumar 100 %."
                ))

    @api.model
    def _periods_overlap(self, first, second):
        return (
            (not first.date_end or first.date_end >= second.date_start)
            and (not second.date_end or second.date_end >= first.date_start)
        )

    def action_end(self):
        today = fields.Date.context_today(self)
        for relation in self:
            if relation.state == "ended":
                continue
            if relation.date_start > today:
                raise UserError(_("No se puede finalizar una relación antes de su fecha inicial."))
            relation.with_context(kabay_allow_history_close=True).write({
                "date_end": today,
                "state": "ended",
            })
        return True
