import base64
import binascii
import mimetypes
import os
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import html_sanitize


PORTAL_MAX_FILE_SIZE = 10 * 1024 * 1024
PORTAL_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt"}
TICKET_STATES = [
    ("new", "Nuevo"), ("review", "En revisión"), ("assigned", "Asignado"),
    ("in_progress", "En progreso"), ("waiting_resident", "En espera del residente"),
    ("resolved", "Resuelto"), ("closed", "Cerrado"), ("cancelled", "Cancelado"),
]
STAFF_GROUPS = (
    "kabay_base.group_kabay_manager",
    "kabay_base.group_kabay_reception",
    "kabay_base.group_kabay_maintenance",
)


class ResCompany(models.Model):
    _inherit = "res.company"

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        if self.env.user.has_group("kabay_base.group_kabay_manager"):
            companies._kabay_ensure_helpdesk_team()
        return companies

    def _kabay_ensure_helpdesk_team(self):
        Team = self.env["helpdesk.team"]
        Stage = self.env["helpdesk.stage"]
        states = [
            ("new", "Nuevo", False), ("review", "En revisión", False),
            ("assigned", "Asignado", False), ("in_progress", "En progreso", False),
            ("waiting_resident", "En espera del residente", False),
            ("resolved", "Resuelto", True), ("closed", "Cerrado", True),
            ("cancelled", "Cancelado", True),
        ]
        for company in self:
            team = Team.search([
                ("company_id", "=", company.id), ("kabay_resident_team", "=", True),
            ], limit=1)
            if not team:
                team = Team.with_company(company).create({
                    "name": "Solicitudes de residentes",
                    "company_id": company.id,
                    "kabay_resident_team": True,
                    "privacy_visibility": "portal",
                    "use_sla": False,
                    "member_ids": [(4, self.env.user.id)],
                })
            stages = Stage.search([("team_ids", "in", team.id), ("kabay_state", "!=", False)])
            for sequence, (code, label, folded) in enumerate(states, start=1):
                stage = stages.filtered(lambda item: item.kabay_state == code)[:1]
                if not stage:
                    Stage.create({
                        "name": label, "sequence": sequence, "fold": folded,
                        "team_ids": [(6, 0, team.ids)], "kabay_state": code,
                    })
                elif stage.name != label or stage.sequence != sequence or stage.fold != folded:
                    stage.write({"name": label, "sequence": sequence, "fold": folded})
            team.write({"name": "Solicitudes de residentes", "privacy_visibility": "portal", "use_sla": False})


class HelpdeskTeam(models.Model):
    _inherit = "helpdesk.team"

    kabay_resident_team = fields.Boolean(string="Equipo Kabay para residentes", copy=False, index=True)


class HelpdeskStage(models.Model):
    _inherit = "helpdesk.stage"

    kabay_state = fields.Selection(TICKET_STATES, string="Estado Kabay", index=True, copy=False)


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    kabay_category_id = fields.Many2one("kabay.helpdesk.category", string="Categoría", index=True, tracking=True)
    kabay_relation_id = fields.Many2one("kabay.apartment.relation", string="Relación residencial", index=True, copy=False)
    kabay_apartment_id = fields.Many2one("kabay.apartment", string="Apartamento", index=True, tracking=True, copy=False)
    kabay_building_id = fields.Many2one("kabay.building", string="Edificio / torre", related="kabay_apartment_id.building_id", store=True, index=True)
    kabay_condominium_id = fields.Many2one("kabay.condominium", related="kabay_apartment_id.condominium_id", store=True, index=True, string="Condominio")
    kabay_state = fields.Selection(related="stage_id.kabay_state", string="Estado Kabay", store=True, index=True)
    kabay_attachment_ids = fields.One2many("kabay.helpdesk.attachment", "ticket_id", string="Archivos residentes")

    @api.model
    def _kabay_is_portal(self):
        return self.env.user.has_group("base.group_portal") and not self.env.user.has_group("base.group_user")

    @api.model
    def _kabay_has_staff_role(self):
        return any(self.env.user.has_group(group) for group in STAFF_GROUPS)

    @api.model
    def _kabay_current_relations(self, partner, apartment=None):
        today = fields.Date.context_today(self)
        domain = [
            ("partner_id", "=", partner.id), ("state", "=", "confirmed"),
            ("active", "=", True), ("role", "in", ["owner", "tenant", "authorized_resident"]),
            ("date_start", "<=", today), "|", ("date_end", "=", False), ("date_end", ">=", today),
        ]
        if apartment:
            domain.append(("apartment_id", "=", apartment.id))
        return self.env["kabay.apartment.relation"].search(domain)

    @api.model
    def _kabay_team_for_company(self, company):
        return self.env["helpdesk.team"].search([
            ("company_id", "=", company.id), ("kabay_resident_team", "=", True),
        ], limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        if self._kabay_is_portal():
            safe_vals = []
            for incoming in vals_list:
                allowed = {"name", "description", "kabay_apartment_id", "kabay_category_id", "priority"}
                if set(incoming) - allowed:
                    # Browser supplied assignment, company, stage, partner or
                    # priority values are never trusted or silently honored.
                    incoming = {key: value for key, value in incoming.items() if key in allowed}
                try:
                    apartment = self.env["kabay.apartment"].browse(int(incoming.get("kabay_apartment_id", 0))).exists()
                except (TypeError, ValueError):
                    apartment = self.env["kabay.apartment"]
                if not apartment:
                    raise ValidationError(_("Seleccione un apartamento válido."))
                relation = self._kabay_current_relations(self.env.user.partner_id, apartment)[:1]
                if not relation or apartment.company_id not in self.env.companies:
                    raise AccessError(_("No tiene una relación residencial vigente con ese apartamento."))
                category = self.env["kabay.helpdesk.category"].browse(int(incoming.get("kabay_category_id", 0))).exists()
                if not category or not category.active or category.company_id and category.company_id != apartment.company_id:
                    raise ValidationError(_("Seleccione una categoría activa para su compañía."))
                priority = str(incoming.get("priority", "1"))
                if priority not in {"0", "1", "2", "3"}:
                    raise ValidationError(_("Seleccione una prioridad válida."))
                team = self._kabay_team_for_company(apartment.company_id)
                if not team:
                    raise UserError(_("No hay un equipo de solicitudes configurado para esta compañía."))
                stage = team.stage_ids.filtered(lambda item: item.kabay_state == "new")[:1]
                if not stage:
                    raise UserError(_("El equipo no tiene configurada la etapa inicial."))
                safe_vals.append({
                    "name": (incoming.get("name") or "").strip(),
                    "description": html_sanitize(incoming.get("description") or ""),
                    "partner_id": self.env.user.partner_id.id,
                    "kabay_relation_id": relation.id,
                    "kabay_apartment_id": apartment.id,
                    "kabay_category_id": category.id,
                    "team_id": team.id,
                    "stage_id": stage.id,
                    "priority": priority,
                })
            vals_list = safe_vals
        return super().create(vals_list)

    def write(self, vals):
        if self._kabay_is_portal():
            # Odoo's PortalMixin uses its standard superuser token routine
            # during ticket creation; this remains limited to access_token.
            if self.env.su and set(vals) == {"access_token"}:
                return super().write(vals)
            if vals:
                raise AccessError(_("El Portal no puede modificar directamente la solicitud."))
            return super().write(vals)
        if "stage_id" in vals:
            if not self._kabay_has_staff_role():
                raise AccessError(_("No tiene permiso para cambiar el estado de solicitudes."))
            target = self.env["helpdesk.stage"].browse(vals["stage_id"])
            for ticket in self:
                if target not in ticket.team_id.stage_ids:
                    raise ValidationError(_("La etapa no pertenece al equipo responsable."))
                old_state = ticket.kabay_state or "new"
                new_state = target.kabay_state
                if not self._kabay_transition_allowed(old_state, new_state):
                    raise UserError(_("La transición de estado solicitada no está permitida."))
        if {"partner_id", "kabay_apartment_id", "kabay_relation_id"} & set(vals):
            if self.filtered(lambda ticket: ticket.kabay_apartment_id):
                raise AccessError(_("La identidad histórica del solicitante y su apartamento no se pueden sustituir."))
        return super().write(vals)

    @api.model
    def _kabay_transition_allowed(self, old, new):
        transitions = {
            "new": {"review", "assigned", "cancelled"},
            "review": {"assigned", "in_progress", "waiting_resident", "cancelled"},
            "assigned": {"in_progress", "waiting_resident", "cancelled"},
            "in_progress": {"waiting_resident", "resolved", "cancelled"},
            "waiting_resident": {"in_progress", "resolved", "cancelled"},
            "resolved": {"closed", "in_progress"},
            "closed": {"in_progress"},
            "cancelled": set(),
        }
        return new and (new == old or new in transitions.get(old, set()))

    def action_kabay_set_state(self, state=None):
        state = state or self.env.context.get("state")
        if not self._kabay_has_staff_role():
            raise AccessError(_("Solo el personal autorizado puede cambiar el estado."))
        if state not in dict(TICKET_STATES):
            raise ValidationError(_("Estado no válido."))
        stage = self.team_id.stage_ids.filtered(lambda item: item.kabay_state == state)[:1]
        if not stage:
            raise UserError(_("El equipo no tiene una etapa para ese estado."))
        self.write({"stage_id": stage.id})
        return True

    def action_kabay_portal_reopen(self):
        if not self._kabay_is_portal():
            raise AccessError(_("Esta acción es exclusiva del Portal."))
        if any(ticket.partner_id != self.env.user.partner_id or ticket.kabay_state not in ("resolved", "closed") for ticket in self):
            raise AccessError(_("Solo puede reabrir una solicitud propia resuelta o cerrada."))
        stage = self.team_id.stage_ids.filtered(lambda item: item.kabay_state == "in_progress")[:1]
        if not stage:
            raise UserError(_("El equipo no tiene etapa de progreso configurada."))
        for ticket in self:
            super(HelpdeskTicket, ticket).write({"stage_id": stage.id})
        return True

    def message_post(self, **kwargs):
        if self._kabay_is_portal():
            if any(ticket.partner_id != self.env.user.partner_id for ticket in self):
                raise AccessError(_("No puede responder solicitudes ajenas."))
            if kwargs.get("subtype_xmlid") not in (None, "mail.mt_comment"):
                raise AccessError(_("El Portal solo puede enviar mensajes visibles para el personal."))
            if kwargs.get("message_type") not in (None, "comment"):
                raise AccessError(_("Tipo de mensaje no permitido."))
            kwargs["subtype_xmlid"] = "mail.mt_comment"
            kwargs["message_type"] = "comment"
            kwargs["partner_ids"] = []
            kwargs["body"] = html_sanitize(kwargs.get("body") or "")
        return super().message_post(**kwargs)

    def _kabay_portal_check_access(self):
        self.ensure_one()
        if not self._kabay_is_portal() or self.partner_id != self.env.user.partner_id:
            raise AccessError(_("No tiene acceso a esta solicitud."))
        if self.company_id not in self.env.companies:
            raise AccessError(_("La solicitud no pertenece a una compañía autorizada."))
        self.check_access("read")
        return True

    def _kabay_public_messages(self):
        self.ensure_one()
        internal_note = self.env.ref("mail.mt_note")
        return self.website_message_ids.filtered(
            lambda message: not message.subtype_id.internal and message.subtype_id != internal_note
        )


class KabayHelpdeskAttachment(models.Model):
    _name = "kabay.helpdesk.attachment"
    _description = "Adjunto privado de solicitud residencial"
    _order = "create_date desc"

    name = fields.Char(required=True, string="Nombre")
    ticket_id = fields.Many2one("helpdesk.ticket", required=True, ondelete="cascade", index=True, string="Solicitud")
    company_id = fields.Many2one(related="ticket_id.company_id", store=True, index=True, string="Compañía")
    datas = fields.Binary(required=True, attachment=True, string="Archivo")
    file_size = fields.Integer(required=True, readonly=True, string="Tamaño del archivo")
    mimetype = fields.Char(readonly=True, string="Tipo MIME")

    @api.model_create_multi
    def create(self, vals_list):
        is_portal = self.env.user.has_group("base.group_portal") and not self.env.user.has_group("base.group_user")
        cleaned = []
        for vals in vals_list:
            ticket = self.env["helpdesk.ticket"].browse(vals.get("ticket_id")).exists()
            if not ticket:
                raise ValidationError(_("La solicitud seleccionada no existe."))
            if is_portal:
                ticket._kabay_portal_check_access()
                if ticket.kabay_state in ("closed", "cancelled"):
                    raise AccessError(_("No se permiten archivos en solicitudes cerradas."))
            filename = os.path.basename(vals.get("name", ""))
            extension = os.path.splitext(filename)[1].lower()
            if extension not in PORTAL_ALLOWED_EXTENSIONS:
                raise ValidationError(_("Tipo de archivo no permitido."))
            encoded = vals.get("datas") or b""
            if isinstance(encoded, str):
                try:
                    encoded = encoded.encode("ascii")
                except UnicodeEncodeError:
                    raise ValidationError(_("El archivo no tiene un formato válido.")) from None
            # Reject over-sized RPC payloads before allocating the decoded copy.
            max_encoded_size = ((PORTAL_MAX_FILE_SIZE + 2) // 3) * 4
            if len(encoded) > max_encoded_size:
                raise ValidationError(_("El archivo está vacío o excede el límite de 10 MB."))
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                raise ValidationError(_("El archivo no tiene un formato válido.")) from None
            if not raw or len(raw) > PORTAL_MAX_FILE_SIZE:
                raise ValidationError(_("El archivo está vacío o excede el límite de 10 MB."))
            cleaned.append({
                "name": filename,
                "ticket_id": ticket.id,
                "datas": vals["datas"],
                "file_size": len(raw),
                "mimetype": mimetypes.guess_type(filename)[0] or "application/octet-stream",
            })
        return super().create(cleaned)

    def unlink(self):
        if self.env.user.has_group("base.group_portal") and not self.env.user.has_group("base.group_user"):
            raise AccessError(_("El Portal no puede eliminar archivos."))
        return super().unlink()
