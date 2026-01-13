from odoo import  fields, models


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    bool_stock_move_line = fields.Boolean(string='Stock Move Line Flag',default=False)