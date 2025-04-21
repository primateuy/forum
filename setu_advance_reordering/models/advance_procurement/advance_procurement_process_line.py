from odoo import fields, models, api, _


class AdvanceProcurementProcessLine(models.Model):
    _name = 'advance.procurement.process.line'
    _description = "Advance Procurement Lines"

    product_id = fields.Many2one('product.product', string="Product")
    warehouse_id = fields.Many2one('stock.warehouse', string="WH", help='Warehouse')
    # carton_qty = fields.Integer('Carton Quantity')
    average_daily_sale = fields.Float('ADS', help="Average daily sale")
    available_stock = fields.Float('Free qty', help='Available Quantity - Outgoing')
    transit_time_sales = fields.Float('Transit sales', help="Sales possibility during the order transit period")
    stock_after_transit = fields.Float('Stock after transit', help="Remaining stock when order reached at warehouse")
    expected_sales = fields.Float('Coverage days sales',
                                  help="Sales possibility during the transit days or coverage days")
    demanded_qty = fields.Float('Demand',
                                help="Security days sales - Stock after transit, set 0 if found negative else put the calculated value ")
    # demanded_cartoon_qty = fields.Float('Demanded Cartoon Quantity')
    order_qty = fields.Float('Ordered Quantity')
    wh_sharing_percentage = fields.Float('Warehouse sharing (%)')
    procurement_process_id = fields.Many2one('advance.procurement.process', string="Replenishment process")
    turnover_ratio = fields.Float("Turnover ratio")
    fsn_classification = fields.Char("FSN")
    xyz_classification = fields.Char("XYZ")
    combine_classification = fields.Char("FSN-XYZ")
    incoming_qty = fields.Float('Incoming', help='Incoming quantity')
    demand_adjustment_qty = fields.Integer('To be delivered')
    stock_move_ids = fields.Many2many('stock.move', string='Stock Move')

    def action_incoming_qty_stock_move(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "setu_advance_reordering.actions_advance_reorder_stock_move")
        action['domain'] = [('id', 'in', self.stock_move_ids.ids)]
        return action
