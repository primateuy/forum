from odoo import models, fields

class AccountJournal(models.Model):
    _inherit = "account.journal"

    id_ksi_locations_group = fields.Char("ID Integración Cámaras (KSI)", help="Identificador del Locations Group en KSI Vision")
