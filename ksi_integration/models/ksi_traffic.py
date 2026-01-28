from odoo import models, fields


class KsiTraffic(models.Model):
    _name = "ksi.traffic"
    _description = "Tránsito de Personas – KSI"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _check_company_auto = True
    _order = "journal_id, fecha_hora asc"

    company_id = fields.Many2one("res.company", 'Company', required=True, default=lambda self: self.env.company)
    journal_id = fields.Many2one("account.journal", "Diario de Venta", check_company=True, tracking=True)
    id_ksi = fields.Char(related='journal_id.id_ksi_locations_group', readonly=True, store=True, string='ID')
    fecha_hora = fields.Datetime("Fecha y Hora", tracking=True)
    fecha = fields.Date("Fecha", tracking=True)
    hora = fields.Char("Hora", tracking=True)
    time_code = fields.Char('TIME FRAME FORM SERVICE', index=True)
    sum_forwards_is_entrance = fields.Integer('sum_forwards_isEntrance', tracking=True)
    sum_forwards_is_external_flow = fields.Integer('sum_forwards_isExternalFlow', tracking=True)
    last_ws_update = fields.Datetime('Última Consulta WS', tracking=True)
