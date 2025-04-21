from odoo import fields, models, api
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta


class ProductSalesHistory(models.Model):
    _name = "product.iwt.history"
    _description = """update product IWT history
    -This model is used to keep the product IWT history which we highlight in order points
    -IWT history will be updated time to time by cron or manual"""

    picking_id = fields.Many2one('stock.picking', string='Picking')
    product_id = fields.Many2one("product.product", "Product")
    date = fields.Date("Date")
    qty = fields.Float("Qty")
    warehouse_id = fields.Many2one("stock.warehouse", "Warehouse")
    orderpoint_id = fields.Many2one("stock.warehouse.orderpoint", "Order Point", ondelete='cascade')
    lead_time = fields.Float("Lead Time")

    def update_product_iwt_history(self):
        end_date = datetime.now().date()
        start_date = end_date.replace(day=4)

        query = """
                    Select * from update_product_iwt_history('{}','{}','%s','%s','%s')
                    """ % (
            start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), self.env.user.id)
        self._cr.execute(query)
        orderpoints = self.env['stock.warehouse.orderpoint'].search([])
        orderpoints and orderpoints._calculate_lead_time()
