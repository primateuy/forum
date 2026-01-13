from odoo import  fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    bool_move_flag = fields.Boolean(string='Move Flag',default=False)
