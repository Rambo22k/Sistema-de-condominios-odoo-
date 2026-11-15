import base64
from odoo import Command, api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


NOTICE_TYPES = [
    ("general", "Comunicado general"),
    ("maintenance", "Mantenimiento"),
    ("services", "Interrupción de servicios"),
    ("security", "Seguridad"),
    ("emergency", "Emergencia"),
    ("community", "Actividades comunitarias"),
    ("administration", "Cobros y administración"),
    ("other", "Otros"),
]
NOTICE_PRIORITIES = [("normal", "Normal"), ("important", "Importante"), ("urgent", "Urgente")]
NOTICE_STATES = [
    ("draft", "Borrador"),
    ("scheduled", "Programado"),
    ("publishing", "En publicación"),
    ("published", "Publicado"),
    ("finished", "Finalizado"),
    ("cancelled", "Cancelado"),
]
NOTICE_SCOPES = [
    ("company", "Todos los condominios de la compañía"),
    ("condominium", "Condominio"),
    ("building", "Torre o edificio"),
    ("apartments", "Apartamentos específicos"),
    ("contacts", "Personas específicas"),
]
RESIDENT_ROLES = [
    ("all", "Todos los residentes autorizados"),
    ("owner", "Propietarios"),
    ("tenant", "Inquilinos"),
    ("authorized_resident", "Residentes autorizados"),
]
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".doc", ".docx", ".odt", ".xls", ".xlsx"}
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


class KabayNotice(models.Model):
    _name = "kabay.notice"
    _description = "Aviso comunitario Kabay"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "publish_datetime desc, id desc"
    _check_company_auto = True

    name = fields.Char(string="Título", required=True, tracking=True)
    reference = fields.Char(string="Referencia", required=True, default="Nuevo", copy=False, index=True, tracking=True)
    summary = fields.Char(string="Resumen", required=True, tracking=True)
    content = fields.Html(string="Contenido", required=True, sanitize=True, sanitize_overridable=False)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True, tracking=True)
    condominium_id = fields.Many2one("kabay.condominium", string="Condominio", ondelete="restrict", index=True, tracking=True, check_company=True)
    publication_condominium_ids = fields.Many2many(
        "kabay.condominium", "kabay_notice_publication_condominium_rel", "notice_id", "condominium_id",
        string="Condominios autorizados al programar", copy=False,
        groups="kabay_base.group_kabay_manager",
    )
    publication_scope_locked = fields.Boolean(string="Alcance de publicación congelado", copy=False, groups="kabay_base.group_kabay_manager")
    building_id = fields.Many2one("kabay.building", string="Torre / edificio", ondelete="restrict", index=True, tracking=True, check_company=True)
    scope = fields.Selection(NOTICE_SCOPES, required=True, default="condominium", tracking=True)
    apartment_ids = fields.Many2many(
        "kabay.apartment", "kabay_notice_apartment_rel", "notice_id", "apartment_id",
        string="Apartamentos", check_company=True,
    )
    target_partner_ids = fields.Many2many(
        "res.partner", "kabay_notice_partner_rel", "notice_id", "partner_id", string="Residentes específicos",
    )
    target_role = fields.Selection(RESIDENT_ROLES, required=True, default="all", string="Tipo de residente", tracking=True)
    notice_type = fields.Selection(NOTICE_TYPES, required=True, default="general", tracking=True)
    priority = fields.Selection(NOTICE_PRIORITIES, required=True, default="normal", tracking=True)
    state = fields.Selection(NOTICE_STATES, required=True, default="draft", index=True, tracking=True)
    create_user_id = fields.Many2one("res.users", string="Creado por", default=lambda self: self.env.user, readonly=True)
    published_by_id = fields.Many2one("res.users", string="Publicado por", readonly=True, tracking=True)
    published_at = fields.Datetime(string="Fecha de publicación efectiva", readonly=True, tracking=True)
    publish_datetime = fields.Datetime(string="Publicar el", required=True, default=fields.Datetime.now, tracking=True)
    expiration_datetime = fields.Datetime(string="Vence el", tracking=True)
    cancelled_by_id = fields.Many2one("res.users", string="Cancelado por", readonly=True, tracking=True)
    cancelled_at = fields.Datetime(string="Fecha de cancelación", readonly=True, tracking=True)
    publication_error = fields.Text(string="Último problema de publicación", readonly=True, groups="kabay_base.group_kabay_manager")
    document_ids = fields.One2many("kabay.notice.document", "notice_id", string="Archivos")
    recipient_ids = fields.One2many("kabay.notice.recipient", "notice_id", string="Destinatarios")
    read_ids = fields.One2many("kabay.notice.read", "notice_id", string="Lecturas")
    recipient_count = fields.Integer(compute="_compute_read_statistics", compute_sudo=True, groups="kabay_base.group_kabay_manager,kabay_base.group_kabay_management")
    read_count = fields.Integer(compute="_compute_read_statistics", compute_sudo=True, groups="kabay_base.group_kabay_manager,kabay_base.group_kabay_management")
    pending_count = fields.Integer(compute="_compute_read_statistics", compute_sudo=True, groups="kabay_base.group_kabay_manager,kabay_base.group_kabay_management")
    read_percentage = fields.Float(compute="_compute_read_statistics", compute_sudo=True, digits=(5, 2), groups="kabay_base.group_kabay_manager,kabay_base.group_kabay_management")

    _reference_uniq = models.Constraint("unique(reference)", "La referencia del aviso debe ser única.")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group("kabay_base.group_kabay_manager") and not self.env.is_system():
            raise AccessError(_("Solo Administración Kabay puede crear avisos."))
        for vals in vals_list:
            if not vals.get("reference") or vals.get("reference") == "Nuevo":
                vals["reference"] = self.env["ir.sequence"].next_by_code("kabay.notice") or "Nuevo"
            vals["state"] = "draft"
            vals["create_user_id"] = self.env.user.id
            vals.pop("publication_condominium_ids", None)
            vals.pop("publication_scope_locked", None)
            for protected in ("published_by_id", "published_at", "cancelled_by_id", "cancelled_at"):
                vals.pop(protected, None)
            vals.pop("publication_error", None)
        notices = super().create(vals_list)
        notices._check_audience_configuration()
        return notices

    def write(self, vals):
        if not self.env.user.has_group("kabay_base.group_kabay_manager") and not self.env.is_system():
            raise AccessError(_("Solo Administración Kabay puede editar avisos."))
        if {"state", "published_at", "published_by_id", "cancelled_at", "cancelled_by_id", "create_user_id", "publication_error"}.intersection(vals):
            raise UserError(_("Use las acciones de publicación para cambiar el estado o la auditoría."))
        if any(notice.state != "draft" for notice in self):
            raise UserError(_("Un aviso programado o publicado no se puede editar. Duplíquelo para emitir una versión nueva."))
        result = super().write(vals)
        self._check_audience_configuration()
        return result

    @api.depends("recipient_ids", "read_ids")
    def _compute_read_statistics(self):
        for notice in self:
            partners = set(notice.recipient_ids.mapped("partner_id").ids)
            read_partners = set(notice.read_ids.mapped("partner_id").ids)
            notice.recipient_count = len(partners)
            notice.read_count = len(partners & read_partners)
            notice.pending_count = max(0, len(partners) - len(partners & read_partners))
            notice.read_percentage = (100.0 * notice.read_count / len(partners)) if partners else 0.0

    @api.constrains("company_id", "condominium_id", "building_id", "scope", "apartment_ids", "target_partner_ids", "target_role", "publish_datetime", "expiration_datetime")
    def _check_notice_configuration(self):
        self._check_audience_configuration()

    def _check_audience_configuration(self, strict=False):
        for notice in self:
            if notice.condominium_id and notice.condominium_id.company_id != notice.company_id:
                raise ValidationError(_("El condominio debe pertenecer a la compañía del aviso."))
            if notice.building_id and (
                notice.building_id.company_id != notice.company_id
                or (notice.condominium_id and notice.building_id.condominium_id != notice.condominium_id)
            ):
                raise ValidationError(_("La torre debe pertenecer al condominio y compañía seleccionados."))
            if any(ap.company_id != notice.company_id for ap in notice.apartment_ids):
                raise ValidationError(_("Los apartamentos no pueden pertenecer a otra compañía."))
            if notice.condominium_id and any(ap.condominium_id != notice.condominium_id for ap in notice.apartment_ids):
                raise ValidationError(_("Todos los apartamentos deben pertenecer al condominio seleccionado."))
            if notice.expiration_datetime and notice.expiration_datetime <= notice.publish_datetime:
                raise ValidationError(_("El vencimiento debe ser posterior a la fecha de publicación."))
            if notice.scope in ("condominium", "building", "apartments", "contacts") and not notice.condominium_id:
                if strict or notice.scope != "condominium":
                    raise ValidationError(_("Seleccione el condominio para este alcance."))
            if notice.scope == "building" and not notice.building_id and strict:
                raise ValidationError(_("Seleccione una torre para este alcance."))
            if notice.scope == "apartments" and not notice.apartment_ids and strict:
                raise ValidationError(_("Seleccione al menos un apartamento."))
            if notice.scope == "contacts" and not notice.target_partner_ids and strict:
                raise ValidationError(_("Seleccione al menos un residente."))
            if notice.scope != "contacts" and notice.target_partner_ids:
                raise ValidationError(_("Los residentes específicos solo se admiten en el alcance Personas específicas."))
            if notice.scope != "apartments" and notice.apartment_ids:
                raise ValidationError(_("Los apartamentos seleccionados solo se admiten en ese alcance."))
            if notice.scope != "building" and notice.building_id:
                raise ValidationError(_("La torre seleccionada solo se admite en ese alcance."))
            if notice.scope == "company" and (notice.condominium_id or notice.building_id or notice.apartment_ids or notice.target_partner_ids):
                raise ValidationError(_("El alcance de compañía no lleva filtros de condominio, torre, apartamento o contacto."))

    def _check_manager_scope(self):
        if self.env.is_system():
            return
        if not self.env.user.has_group("kabay_base.group_kabay_manager"):
            raise AccessError(_("No tiene permiso para administrar avisos."))
        for notice in self:
            condominium = notice.condominium_id or notice.building_id.condominium_id
            if not condominium and notice.apartment_ids:
                condominiums = notice.apartment_ids.mapped("condominium_id")
            elif condominium:
                condominiums = condominium
            else:
                condominiums = self.env["kabay.condominium"]
            if notice.scope != "company" and any(condo.manager_id and condo.manager_id != self.env.user for condo in condominiums):
                raise AccessError(_("El aviso incluye un condominio asignado a otra persona administradora."))

    def _matching_relations(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        domain = [
            ("company_id", "=", self.company_id.id), ("active", "=", True), ("state", "=", "confirmed"),
            ("role", "in", ["owner", "tenant", "authorized_resident"]), ("date_start", "<=", today),
            "|", ("date_end", "=", False), ("date_end", ">=", today),
        ]
        if self.scope == "company" and self.publication_scope_locked:
            domain.append(("condominium_id", "in", self.publication_condominium_ids.ids))
        elif self.scope == "company" and not self.env.is_system():
            domain.extend(["|", ("condominium_id.manager_id", "=", False), ("condominium_id.manager_id", "=", self.env.user.id)])
        if self.scope == "condominium":
            domain.append(("condominium_id", "=", self.condominium_id.id))
        elif self.scope == "building":
            domain.append(("building_id", "=", self.building_id.id))
        elif self.scope == "apartments":
            domain.append(("apartment_id", "in", self.apartment_ids.ids))
        elif self.scope == "contacts":
            domain.extend([("condominium_id", "=", self.condominium_id.id), ("partner_id", "in", self.target_partner_ids.ids)])
        if self.target_role != "all":
            domain.append(("role", "=", self.target_role))
        return self.env["kabay.apartment.relation"].search(domain, order="partner_id, apartment_id, role, id")

    def _materialize_recipients(self):
        self.ensure_one()
        if self.recipient_ids:
            raise UserError(_("La fotografía de destinatarios ya existe y no puede regenerarse."))
        self._check_audience_configuration(strict=True)
        self._check_manager_scope()
        relations = self._matching_relations()
        if self.scope == "contacts":
            eligible_contacts = set(relations.mapped("partner_id").ids)
            requested_contacts = set(self.target_partner_ids.ids)
            if requested_contacts - eligible_contacts:
                raise ValidationError(_("Todos los contactos deben tener una relación residencial vigente en el condominio seleccionado."))
        if not relations:
            raise ValidationError(_("No hay residentes autorizados vigentes para el alcance seleccionado."))
        values = []
        seen = set()
        for relation in relations:
            key = (relation.partner_id.id, relation.apartment_id.id, relation.role)
            if key in seen:
                continue
            seen.add(key)
            values.append({
                "notice_id": self.id, "partner_id": relation.partner_id.id,
                "apartment_id": relation.apartment_id.id, "role": relation.role,
            })
        self.env["kabay.notice.recipient"].create(values)

    def _set_state(self, values):
        return super(KabayNotice, self).write(values)

    def action_publish(self):
        for notice in self:
            notice._check_manager_scope()
            if notice.state not in ("draft", "scheduled"):
                raise UserError(_("Solo un borrador o un aviso programado puede publicarse ahora."))
            notice._check_audience_configuration(strict=True)
            notice.publish_datetime = fields.Datetime.now()
            notice._set_state({"state": "publishing"})
            notice._materialize_recipients()
            notice._set_state({
                "state": "published", "published_by_id": self.env.user.id,
                "published_at": fields.Datetime.now(), "publication_error": False,
            })
            notice.message_post(body=_("Aviso publicado para %s destinatarios.") % notice.recipient_count)
        return True

    def action_schedule(self):
        for notice in self:
            notice._check_manager_scope()
            if notice.state != "draft":
                raise UserError(_("Solo un borrador puede programarse."))
            notice._check_audience_configuration(strict=True)
            if notice.publish_datetime <= fields.Datetime.now():
                raise UserError(_("La fecha programada debe ser futura. Para publicar ahora, use Publicar."))
            if notice.scope == "company":
                if self.env.is_system():
                    allowed_condominiums = self.env["kabay.condominium"].search([("company_id", "=", notice.company_id.id)])
                else:
                    allowed_condominiums = self.env["kabay.condominium"].search([
                        ("company_id", "=", notice.company_id.id),
                        "|", ("manager_id", "=", False), ("manager_id", "=", self.env.user.id),
                    ])
            else:
                condominium = notice.condominium_id or notice.building_id.condominium_id
                allowed_condominiums = condominium or notice.apartment_ids.mapped("condominium_id")
            notice.write({
                "publication_condominium_ids": [Command.set(allowed_condominiums.ids)],
                "publication_scope_locked": True,
            })
            notice._set_state({"state": "scheduled"})
            notice._set_state({"publication_error": False})
            notice.message_post(body=_("Publicación programada para %s.") % fields.Datetime.to_string(notice.publish_datetime))
        return True

    def action_finish(self):
        for notice in self:
            notice._check_manager_scope()
            if notice.state != "published":
                raise UserError(_("Solo un aviso publicado puede finalizarse."))
            notice._set_state({"state": "finished"})
            notice.message_post(body=_("Aviso finalizado por %s.") % self.env.user.display_name)
        return True

    def action_cancel(self):
        for notice in self:
            notice._check_manager_scope()
            if notice.state not in ("scheduled", "published"):
                raise UserError(_("Solo un aviso programado o publicado puede cancelarse."))
            notice._set_state({
                "state": "cancelled", "cancelled_by_id": self.env.user.id,
                "cancelled_at": fields.Datetime.now(),
            })
            notice.message_post(body=_("Aviso cancelado por %s.") % self.env.user.display_name)
        return True

    def action_reset_draft(self):
        for notice in self:
            notice._check_manager_scope()
            if notice.state != "cancelled" or notice.published_at:
                raise UserError(_("Solo puede volver a borrador un aviso cancelado antes de publicarse."))
            self.env["kabay.notice.recipient"].search([("notice_id", "=", notice.id)]).unlink()
            notice._set_state({
                "state": "draft", "cancelled_by_id": False, "cancelled_at": False,
                "publication_condominium_ids": [Command.clear()], "publication_scope_locked": False,
            })
        return True

    @api.model
    def _cron_update_publication_states(self):
        now = fields.Datetime.now()
        expired = self.search([("state", "=", "published"), ("expiration_datetime", "<=", now)])
        for notice in expired:
            notice._set_state({"state": "finished"})
            notice.message_post(body=_("Aviso finalizado automáticamente al vencer."))
        due = self.search([("state", "=", "scheduled"), ("publish_datetime", "<=", now)])
        for notice in due:
            if notice.expiration_datetime and notice.expiration_datetime <= now:
                notice._set_state({"state": "finished"})
                continue
            try:
                notice._set_state({"state": "publishing"})
                notice._materialize_recipients()
            except ValidationError as error:
                is_new_error = notice.publication_error != str(error)
                notice._set_state({"state": "scheduled", "publication_error": str(error)})
                if is_new_error:
                    notice.message_post(body=_("No se pudo publicar automáticamente: %s") % error)
                continue
            notice._set_state({"state": "published", "published_by_id": self.env.user.id, "published_at": now, "publication_error": False})
            notice.message_post(body=_("Aviso publicado automáticamente para %s destinatarios.") % notice.recipient_count)
        return True

    def _portal_check_access(self):
        self.ensure_one()
        if not self.env.user.has_group("base.group_portal"):
            raise AccessError(_("La función Portal es exclusiva para residentes."))
        if not self.recipient_ids.filtered(lambda row: row.partner_id == self.env.user.partner_id):
            raise AccessError(_("Este aviso no está dirigido a su contacto."))
        apartment_ids = self.recipient_ids.filtered(lambda row: row.partner_id == self.env.user.partner_id).mapped("apartment_id").ids
        today = fields.Date.context_today(self)
        current_relation = self.env["kabay.apartment.relation"].search([
            ("partner_id", "=", self.env.user.partner_id.id), ("apartment_id", "in", apartment_ids),
            ("active", "=", True), ("state", "=", "confirmed"),
            ("role", "in", ["owner", "tenant", "authorized_resident"]), ("date_start", "<=", today),
            "|", ("date_end", "=", False), ("date_end", ">=", today),
        ], limit=1)
        if not current_relation:
            raise AccessError(_("Ya no tiene una relación residencial vigente con este aviso."))
        if self.state != "published":
            raise AccessError(_("El aviso no está publicado."))
        if self.expiration_datetime and self.expiration_datetime < fields.Datetime.now():
            raise AccessError(_("Este aviso ya venció."))
        return True

    def action_mark_read(self):
        self.ensure_one()
        self._portal_check_access()
        if not self.env.user.has_group("base.group_portal"):
            raise AccessError(_("Solo el residente destinatario puede registrar su lectura."))
        receipt_model = self.env["kabay.notice.read"]
        receipt = receipt_model.search([
            ("notice_id", "=", self.id), ("partner_id", "=", self.env.user.partner_id.id),
        ], limit=1)
        now = fields.Datetime.now()
        if receipt:
            receipt.write({"last_read_at": now})
        else:
            recipient = self.recipient_ids.filtered(lambda row: row.partner_id == self.env.user.partner_id)[:1]
            receipt_model.create({
                "notice_id": self.id, "partner_id": self.env.user.partner_id.id,
                "user_id": self.env.user.id, "apartment_id": recipient.apartment_id.id,
                "first_read_at": now, "last_read_at": now,
            })
        return True


class KabayNoticeRecipient(models.Model):
    _name = "kabay.notice.recipient"
    _description = "Destinatario histórico de aviso Kabay"
    _order = "notice_id, partner_id, apartment_id"
    _check_company_auto = True

    notice_id = fields.Many2one("kabay.notice", required=True, ondelete="cascade", index=True, check_company=True)
    company_id = fields.Many2one(related="notice_id.company_id", store=True, index=True)
    partner_id = fields.Many2one("res.partner", required=True, ondelete="restrict", index=True)
    apartment_id = fields.Many2one("kabay.apartment", required=True, ondelete="restrict", index=True, check_company=True)
    role = fields.Selection(RESIDENT_ROLES[1:], required=True, index=True)

    _recipient_uniq = models.Constraint("unique(notice_id, partner_id, apartment_id, role)", "El destinatario ya está incluido en el aviso para esa unidad y rol.")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.is_system() and not self.env.user.has_group("kabay_base.group_kabay_manager"):
            raise AccessError(_("Los destinatarios se generan automáticamente al publicar el aviso."))
        for vals in vals_list:
            notice = self.env["kabay.notice"].browse(vals.get("notice_id")).exists()
            if not notice or notice.state != "publishing":
                raise AccessError(_("Los destinatarios solo se crean durante el proceso de publicación."))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(_("La fotografía histórica de destinatarios no se puede editar."))

    def unlink(self):
        if not self.env.is_system() and any(
            row.notice_id.state not in ("draft", "cancelled") or row.notice_id.published_at for row in self
        ):
            raise UserError(_("No se pueden borrar destinatarios de un aviso publicado."))
        return super().unlink()


class KabayNoticeRead(models.Model):
    _name = "kabay.notice.read"
    _description = "Lectura individual de aviso Kabay"
    _order = "first_read_at desc, id desc"
    _check_company_auto = True

    notice_id = fields.Many2one("kabay.notice", required=True, ondelete="cascade", index=True, check_company=True)
    company_id = fields.Many2one(related="notice_id.company_id", store=True, index=True)
    partner_id = fields.Many2one("res.partner", required=True, ondelete="restrict", index=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="restrict", index=True)
    apartment_id = fields.Many2one("kabay.apartment", ondelete="restrict", check_company=True)
    first_read_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    last_read_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    _notice_partner_uniq = models.Constraint("unique(notice_id, partner_id)", "Cada residente tiene un único acuse por aviso.")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group("base.group_portal") and not self.env.is_system():
            raise AccessError(_("Solo el residente puede registrar su propia lectura."))
        for vals in vals_list:
            if not self.env.is_system():
                notice = self.env["kabay.notice"].browse(vals.get("notice_id")).exists()
                if not notice:
                    raise AccessError(_("Aviso no encontrado."))
                notice._portal_check_access()
                if vals.get("partner_id") not in (False, self.env.user.partner_id.id):
                    raise AccessError(_("No puede registrar lecturas a nombre de otra persona."))
                if vals.get("user_id") not in (False, self.env.user.id):
                    raise AccessError(_("No puede registrar lecturas a nombre de otro usuario."))
                vals.update({"partner_id": self.env.user.partner_id.id, "user_id": self.env.user.id})
                vals.pop("first_read_at", None)
                vals.pop("last_read_at", None)
                vals.pop("company_id", None)
                recipient = notice.recipient_ids.filtered(lambda row: row.partner_id == self.env.user.partner_id)[:1]
                vals["apartment_id"] = recipient.apartment_id.id
        return super().create(vals_list)

    def write(self, vals):
        if set(vals) != {"last_read_at"}:
            raise AccessError(_("El acuse identifica al lector y su primera lectura; esos datos no se pueden cambiar."))
        if not self.env.is_system() and any(row.partner_id != self.env.user.partner_id for row in self):
            raise AccessError(_("No puede modificar lecturas de otra persona."))
        if not self.env.is_system():
            vals["last_read_at"] = fields.Datetime.now()
        return super().write(vals)


class KabayNoticeDocument(models.Model):
    _name = "kabay.notice.document"
    _description = "Archivo privado de aviso Kabay"
    _order = "id"
    _check_company_auto = True

    notice_id = fields.Many2one("kabay.notice", required=True, ondelete="cascade", index=True, check_company=True)
    company_id = fields.Many2one(related="notice_id.company_id", store=True, index=True)
    name = fields.Char(required=True)
    file_data = fields.Binary(string="Archivo", required=True, attachment=True)
    file_name = fields.Char(string="Nombre del archivo", required=True)
    file_size = fields.Integer(compute="_compute_file_size")

    @api.depends("file_data")
    def _compute_file_size(self):
        for document in self:
            try:
                document.file_size = len(base64.b64decode(document.file_data or b""))
            except (ValueError, TypeError):
                document.file_size = 0

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group("kabay_base.group_kabay_manager") and not self.env.is_system():
            raise AccessError(_("Solo Administración Kabay puede adjuntar archivos."))
        for vals in vals_list:
            notice = self.env["kabay.notice"].browse(vals.get("notice_id")).exists()
            if not notice or notice.state != "draft":
                raise UserError(_("Solo se pueden adjuntar archivos a un aviso en borrador."))
            self._validate_file(vals)
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.user.has_group("kabay_base.group_kabay_manager") and not self.env.is_system():
            raise AccessError(_("Solo Administración Kabay puede modificar archivos."))
        if any(document.notice_id.state != "draft" for document in self):
            raise UserError(_("Los archivos quedan congelados cuando se programa o publica el aviso."))
        if "notice_id" in vals:
            notice = self.env["kabay.notice"].browse(vals["notice_id"]).exists()
            if not notice or notice.state != "draft":
                raise UserError(_("Los archivos solo pueden enlazarse a un borrador."))
        if "file_name" in vals or "file_data" in vals:
            self._validate_file(vals)
        return super().write(vals)

    @api.model
    def _validate_file(self, vals):
        file_name = vals.get("file_name")
        file_data = vals.get("file_data")
        if file_name:
            extension = "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
            if extension not in ALLOWED_EXTENSIONS:
                raise ValidationError(_("Tipo de archivo no permitido. Use PDF, imágenes o documentos ofimáticos."))
        if file_data:
            try:
                decoded = base64.b64decode(file_data, validate=True)
            except (ValueError, TypeError):
                raise ValidationError(_("El archivo no tiene un formato válido."))
            if not decoded or len(decoded) > MAX_DOCUMENT_BYTES:
                raise ValidationError(_("El archivo debe tener contenido y no superar 20 MB."))

    def unlink(self):
        if any(document.notice_id.state != "draft" for document in self):
            raise UserError(_("No se pueden borrar archivos de un aviso programado o publicado."))
        return super().unlink()
