from dateutil import relativedelta
from odoo import fields, models, api, _


class AdvanceReorderOrderProcessConfig(models.Model):
    _name = 'advance.reorder.orderprocess.config'
    _description = "Advance Reorder with Demand Generation Configuration"

    warehouse_group_id = fields.Many2one('stock.warehouse.group', string="Warehouse group")
    default_warehouse_id = fields.Many2one('stock.warehouse', string="Default warehouse",
                                           help="Set warehouse where order has to be delivered")
    vendor_lead_days = fields.Integer('Lead days', help="Estimated shipment arrival days")
    reorder_process_id = fields.Many2one('advance.reorder.orderprocess', string="Advance reorder process")
    reorder_process_template_id = fields.Many2one('advance.reorder.planner', string="Advance reorder process")
    order_date = fields.Date('Order date', help="Order date")
    order_arrival_date = fields.Date('Order arrival date')
    advance_stock_start_date = fields.Date('Coverage days start', help="Coverage days start")
    advance_stock_end_date = fields.Date('Coverage days end', help="Coverage days end")

    _sql_constraints = [
        ('unique_wh_group_reorder_wise', 'UNIQUE(warehouse_group_id, reorder_process_id)',
         'Warehouse group has been already added in reorder process.')
    ]

    @api.onchange('vendor_lead_days')
    def onchange_vendor_lead_days(self):
        if self.reorder_process_id:
            self.order_date = self.reorder_process_id.reorder_date.date()
            days = self.vendor_lead_days - 1 if self.vendor_lead_days > 0.0 else self.vendor_lead_days
            self.order_arrival_date = (self.order_date +
                                       relativedelta.relativedelta(days=days)).strftime("%Y-%m-%d")

    @api.onchange('order_arrival_date')
    def onchange_order_arrival_date(self):
        if self.reorder_process_id:
            self.advance_stock_start_date = (self.order_arrival_date +
                                             relativedelta.relativedelta(days=1)).strftime("%Y-%m-%d")
            days = self.reorder_process_id.buffer_security_days - 1 \
                if self.reorder_process_id.buffer_security_days > 0.0 \
                else self.reorder_process_id.buffer_security_days
            self.advance_stock_end_date = (self.advance_stock_start_date +
                                           relativedelta.relativedelta(days=days)).strftime("%Y-%m-%d")
