from odoo import fields, models, api, _


class AdvanceReorderOrderProcessLine(models.Model):
    _name = 'advance.reorder.orderprocess.line'
    _description = "Advance Reorder with Demand Generation Lines"

    product_id = fields.Many2one('product.product', string="Product")
    warehouse_group_id = fields.Many2one('stock.warehouse.group', string="WH Group", help="Warehouse Group")
    # carton_qty = fields.Integer('Carton Qty', help="Cartoon Quantity")
    average_daily_sale = fields.Float('ADS', help="Average daily sales")
    available_stock = fields.Integer('Free qty', help="Available Stock - Outgoing")
    transit_time_sales = fields.Float('Transit sales', help="Sales possibility during the order transit period")
    stock_after_transit = fields.Float('Stock after transit', help="Remaining stock when order reached at warehouse")
    expected_sales = fields.Float('Coverage days sales', help="Sales possibility during the coverage days")
    demanded_qty = fields.Float('Demand',
                                help="Security days sales - Stock after transit, set 0 if found negative else put the calculated value ")
    # demanded_cartoon_qty = fields.Float('Cartoon Demand')
    wh_sharing_percentage = fields.Float('WH Group sharing percentage')
    reorder_process_id = fields.Many2one('advance.reorder.orderprocess', string="Reorder process")
    turnover_ratio = fields.Float("Turnover Ratio")
    fsn_classification = fields.Char("FSN")
    xyz_classification = fields.Char("XYZ")
    combine_classification = fields.Char("FSN-XYZ")
    incoming_qty = fields.Float('Incoming', help='Incoming quantity')
    demand_adjustment_qty = fields.Integer('To be ordered')
    stock_move_ids = fields.Many2many('stock.move', string='Stock Move')

    def action_incoming_qty_stock_move(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "setu_advance_reordering.actions_advance_reorder_stock_move")
        action['domain'] = [('id', 'in', self.stock_move_ids.ids)]
        return action
