from odoo import api, fields, models
from odoo.exceptions import ValidationError


class KabayApartment(models.Model):
    _name = "kabay.apartment"
    _description = "Apartamento de condominio"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "condominium_id, building_id, name, id"

    name = fields.Char(string="Nombre o número de unidad", required=True, tracking=True)
    code = fields.Char(string="Código", required=True, copy=False, tracking=True)
    building_id = fields.Many2one(
        "kabay.building", string="Edificio / torre", required=True, ondelete="restrict", index=True, tracking=True
    )
    condominium_id = fields.Many2one(
        "kabay.condominium", related="building_id.condominium_id", store=True, index=True
    , string="Condominio")
    company_id = fields.Many2one(
        "res.company", related="building_id.company_id", store=True, index=True
    , string="Compañía")
    floor = fields.Char(string="Piso")
    unit_type = fields.Char(string="Tipo de unidad")
    area = fields.Float(digits=(16, 2), string="Área (m²)")
    coefficient = fields.Float(digits=(16, 6), string="Coeficiente de participación")
    photo_ids = fields.One2many("kabay.apartment.photo", "apartment_id", string="Fotos")
    photo_count = fields.Integer(compute="_compute_photo_count", string="Cantidad de fotos")
    active = fields.Boolean(default=True, tracking=True, string="Activo")
    notes = fields.Text(string="Notas")

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

    @api.onchange("building_id")
    def _onchange_building_id_code(self):
        """Build a unit code from its tower and local apartment name."""
        for apartment in self:
            if apartment.building_id and apartment.name:
                apartment.code = apartment._make_unit_code(apartment.building_id, apartment.name)

    @api.onchange("name")
    def _onchange_name_code(self):
        for apartment in self:
            prefix = "%s-" % apartment.building_id.code if apartment.building_id else False
            if apartment.building_id and apartment.name and (
                not apartment.code or apartment.code.startswith(prefix)
            ):
                apartment.code = apartment._make_unit_code(apartment.building_id, apartment.name)

    @api.model
    def _make_unit_code(self, building, apartment_name):
        tower_code = (building.code or "").strip()
        unit_label = "-".join((apartment_name or "").strip().split())
        return "%s-%s" % (tower_code, unit_label) if tower_code and unit_label else ""

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
                raise ValidationError("El apartamento debe pertenecer al condominio de su edificio.")


class KabayApartmentPhoto(models.Model):
    _name = "kabay.apartment.photo"
    _description = "Foto del apartamento"
    _order = "sequence, id"

    name = fields.Char(string="Descripción", required=True)
    apartment_id = fields.Many2one(
        "kabay.apartment", required=True, ondelete="restrict", index=True
    , string="Apartamento")
    company_id = fields.Many2one(
        "res.company", related="apartment_id.company_id", store=True, index=True
    , string="Compañía")
    image = fields.Image(required=True, attachment=True, string="Imagen")
    sequence = fields.Integer(default=10, string="Secuencia")

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
                raise ValidationError("Un apartamento puede tener como máximo 10 fotos.")
        return super().create(vals_list)

    def write(self, vals):
        if "apartment_id" not in vals:
            return super().write(vals)
        target_id = vals["apartment_id"]
        if not target_id:
            raise ValidationError("La foto debe permanecer vinculada a un apartamento.")
        moving = self.filtered(lambda photo: photo.apartment_id.id != target_id)
        apartment_ids = set(moving.mapped("apartment_id").ids) | {target_id}
        self._lock_apartments(apartment_ids)
        target_count = self.search_count([("apartment_id", "=", target_id)])
        if target_count + len(moving) > 10:
            raise ValidationError("Un apartamento puede tener como máximo 10 fotos.")
        return super().write(vals)

    def _lock_apartments(self, apartment_ids):
        if apartment_ids:
            self.env.cr.execute(
                "SELECT id FROM kabay_apartment WHERE id = ANY(%s) ORDER BY id FOR UPDATE",
                [list(apartment_ids)],
            )
