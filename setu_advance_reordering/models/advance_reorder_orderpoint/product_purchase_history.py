from odoo import fields, models, api
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta


class ProductPurchaseHistory(models.Model):
    _name = "product.purchase.history"
    _description = """
    -This model is used to keep product purchase history which we highlights in order points
    -Purchase history will be updated time to time by cron or manual"""

    partner_id = fields.Many2one("res.partner", "Vendor")
    product_id = fields.Many2one("product.product", "Product")
    warehouse_id = fields.Many2one("stock.warehouse", "Warehouse")
    orderpoint_id = fields.Many2one("stock.warehouse.orderpoint", "Order Point", ondelete='cascade')
    purchase_id = fields.Many2one("purchase.order", "Purchase Order")
    po_qty = fields.Float("PO Qty")
    purchase_price = fields.Float("Purchase Price")
    currency_id = fields.Many2one("res.currency", "Currency")
    po_date = fields.Date("Purchase Date")
    lead_time = fields.Float("Lead Time")

    def update_product_purchase_history(self):
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=4)
        query = """
                        Select * from update_product_purchase_history('{}','{}','%s','%s','%s')
                    """ % (
            start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), self.env.user.id)
        self._cr.execute(query)

        self.env['stock.warehouse.orderpoint'].with_context(
            do_not_recalculate_history=True).scheduler_recalculate_data()
        return True
