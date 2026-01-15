from odoo import fields, api, models;


class PickingType(models.Model):
    _inherit = 'stock.picking.type'

    respeta_multiplos = fields.Boolean(string='Respeta Múltiplos', default=False);