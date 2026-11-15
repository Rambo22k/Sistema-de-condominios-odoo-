from odoo import api, fields, models
from odoo.exceptions import ValidationError


class KabayApartment(models.Model):
    _name = "kabay.apartment"
    _description = "Condominium apartment"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "condominium_id, building_id, name, id"

    name = fields.Char(string="Apartment", required=True, tracking=True)
    code = fields.Char(required=True, copy=False, tracking=True)
    building_id = fields.Many2one(
        "kabay.building", required=True, ondelete="restrict", index=True, tracking=True
    )
    condominium_id = fields.Many2one(
        "kabay.condominium", related="building_id.condominium_id", store=True, index=True
    )
    company_id = fields.Many2one(
        "res.company", related="building_id.company_id", store=True, index=True
    )
    floor = fields.Char()
    unit_type = fields.Char(string="Unit type")
    area = fields.Float(digits=(16, 2), string="Area (m²)")
    coefficient = fields.Float(digits=(16, 6), string="Participation coefficient")
    photo_ids = fields.One2many("kabay.apartment.photo", "apartment_id", string="Photos")
    photo_count = fields.Integer(compute="_compute_photo_count")
    active = fields.Boolean(default=True, tracking=True)
    notes = fields.Text()

    def action_add_relation(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Añadir persona",
            "res_model": "kabay.apartment.relation",
            "view_mode": "form",
            "target": "current",
            "context": {"default_apartment_id": self.id},
        }

    _code_building_uniq = models.Constraint(
        "unique(code, building_id)", "An apartment code must be unique per building."
    )

    @api.depends("photo_ids")
    def _compute_photo_count(self):
        for record in self:
            record.photo_count = len(record.photo_ids)

    @api.constrains("building_id", "condominium_id")
    def _check_building_condominium(self):
        for record in self:
            if not record.building_id or record.condominium_id != record.building_id.condominium_id:
                raise ValidationError("An apartment must belong to its building's condominium.")


class KabayApartmentPhoto(models.Model):
    _name = "kabay.apartment.photo"
    _description = "Apartment photo"
    _order = "sequence, id"

    name = fields.Char(required=True)
    apartment_id = fields.Many2one(
        "kabay.apartment", required=True, ondelete="restrict", index=True
    )
    company_id = fields.Many2one(
        "res.company", related="apartment_id.company_id", store=True, index=True
    )
    image = fields.Image(required=True, attachment=True)
    sequence = fields.Integer(default=10)

    @api.model_create_multi
    def create(self, vals_list):
        counts = {}
        for vals in vals_list:
            apartment_id = vals.get("apartment_id")
            if apartment_id:
                counts[apartment_id] = counts.get(apartment_id, 0) + 1
        self._lock_apartments(counts)
        for apartment_id, incoming in counts.items():
            existing = self.search_count([("apartment_id", "=", apartment_id)])
            if existing + incoming > 10:
                raise ValidationError("An apartment can have at most 10 photos.")
        return super().create(vals_list)

    def write(self, vals):
        if "apartment_id" not in vals:
            return super().write(vals)
        target_id = vals["apartment_id"]
        if not target_id:
            raise ValidationError("A photo must remain linked to an apartment.")
        moving = self.filtered(lambda photo: photo.apartment_id.id != target_id)
        apartment_ids = set(moving.mapped("apartment_id").ids) | {target_id}
        self._lock_apartments(apartment_ids)
        target_count = self.search_count([("apartment_id", "=", target_id)])
        if target_count + len(moving) > 10:
            raise ValidationError("An apartment can have at most 10 photos.")
        return super().write(vals)

    def _lock_apartments(self, apartment_ids):
        if apartment_ids:
            self.env.cr.execute(
                "SELECT id FROM kabay_apartment WHERE id = ANY(%s) ORDER BY id FOR UPDATE",
                [list(apartment_ids)],
            )
