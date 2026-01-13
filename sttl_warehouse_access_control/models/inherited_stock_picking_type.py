from odoo import  fields, models


class InheritedStockPicking(models.Model):
    _inherit = "stock.picking.type"

    bool_picking_type = fields.Boolean(string='Picking Flag',default=False)

