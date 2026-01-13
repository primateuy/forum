from odoo import  fields, models


class InheritedPicking(models.Model):
    _inherit = "stock.picking"

    bool_picking_flag = fields.Boolean(string='Picking Flag',default=False)