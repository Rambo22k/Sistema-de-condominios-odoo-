from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class KabayNotificationSettings(models.Model):
    _name = "kabay.notification.settings"
    _description = "Configuración de comunicaciones Kabay"
    _order = "company_id"

    company_id = fields.Many2one("res.company", required=True, ondelete="cascade", index=True, string="Compañía")
    active = fields.Boolean(default=True, string="Activo")
    delivery_enabled = fields.Boolean(
        string="Permitir encolar correos",
        default=False,
        help="Solo habilite después de configurar y verificar el correo saliente nativo de Odoo.",
    )
    billing_enabled = fields.Boolean(default=True, string="Habilitar facturación")
    deposits_enabled = fields.Boolean(default=True, string="Habilitar depósitos")
    helpdesk_enabled = fields.Boolean(default=True, string="Habilitar solicitudes")
    notices_enabled = fields.Boolean(default=True, string="Habilitar avisos")
    financing_enabled = fields.Boolean(default=True, string="Habilitar financiamiento")
    reminder_days_before_first = fields.Integer(default=7, string="Días antes para el primer recordatorio")
    reminder_days_before_second = fields.Integer(default=3, string="Días antes para el segundo recordatorio")
    reminder_days_before_due = fields.Integer(default=0, string="Días antes del vencimiento")
    reminder_days_after = fields.Integer(default=7, string="Días después del vencimiento")
    max_attempts = fields.Integer(default=3, string="Máximo de intentos")
    retry_minutes = fields.Integer(default=30, string="Minutos entre reintentos")
    billing_template_id = fields.Many2one("mail.template", string="Plantilla de facturación")
    deposits_template_id = fields.Many2one("mail.template", string="Plantilla de depósitos")
    helpdesk_template_id = fields.Many2one("mail.template", string="Plantilla de solicitudes")
    notices_template_id = fields.Many2one("mail.template", string="Plantilla de avisos")
    financing_template_id = fields.Many2one("mail.template", string="Plantilla de financiamiento")
    smtp_ready = fields.Boolean(compute="_compute_smtp_ready", string="Correo saliente disponible")

    _company_uniq = models.Constraint("unique(company_id)", "Ya existe una configuración para esta compañía.")

    @api.depends("company_id", "delivery_enabled")
    def _compute_smtp_ready(self):
        Server = self.env["ir.mail_server"].sudo()
        for setting in self:
            domain = [("active", "=", True)]
            if "company_id" in Server._fields and setting.company_id:
                domain += ["|", ("company_id", "=", False), ("company_id", "=", setting.company_id.id)]
            setting.smtp_ready = bool(Server.search_count(domain))

    @api.constrains(
        "reminder_days_before_first", "reminder_days_before_second", "reminder_days_before_due",
        "reminder_days_after", "max_attempts", "retry_minutes",
    )
    def _check_intervals(self):
        for setting in self:
            before = [
                setting.reminder_days_before_first,
                setting.reminder_days_before_second,
                setting.reminder_days_before_due,
            ]
            if any(value < 0 for value in before) or setting.reminder_days_after < 0:
                raise ValidationError(_("Los intervalos de recordatorio deben ser días no negativos."))
            if len(set(before)) != len(before):
                raise ValidationError(_("Los tres intervalos previos deben ser distintos."))
            if setting.reminder_days_after < 1:
                raise ValidationError(_("El recordatorio posterior al vencimiento debe ser al menos un día después."))
            if setting.max_attempts < 1 or setting.max_attempts > 10:
                raise ValidationError(_("Los intentos permitidos deben estar entre 1 y 10."))
            if setting.retry_minutes < 1 or setting.retry_minutes > 10080:
                raise ValidationError(_("La espera de reintento debe estar entre 1 minuto y 7 días."))

    def write(self, vals):
        if not self.env.is_system() and not self.env.user.has_group("kabay_base.group_kabay_manager"):
            raise AccessError(_("Solo Administración Kabay puede cambiar la configuración de comunicaciones."))
        if "company_id" in vals and any(setting.company_id.id != vals["company_id"] for setting in self):
            raise AccessError(_("La compañía de una configuración existente no se puede sustituir."))
        return super().write(vals)

    @api.model
    def _for_company(self, company):
        company.ensure_one()
        setting = self.sudo().search([("company_id", "=", company.id)], limit=1)
        if not setting:
            setting = self.sudo().create({"company_id": company.id})
        return setting

    def _template_for(self, category):
        self.ensure_one()
        field_name = {
            "billing": "billing_template_id",
            "deposits": "deposits_template_id",
            "helpdesk": "helpdesk_template_id",
            "notices": "notices_template_id",
            "financing": "financing_template_id",
        }[category]
        return self[field_name]
