from odoo import  api, fields, models



class StockQuant(models.Model):
    _inherit = 'stock.quant'

    boolean_quant_flag = fields.Boolean(string='Flag',default=False)