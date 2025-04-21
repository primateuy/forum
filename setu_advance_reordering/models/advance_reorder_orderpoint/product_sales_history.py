from odoo import fields, models, api
from datetime import datetime, timedelta
import calendar
from dateutil.relativedelta import relativedelta


class ProductSalesHistory(models.Model):
    _name = "product.sales.history"
    _description = """update_product_sales_history
    -This model is used to keep the product sales history which we highlights in order points
    -Sales history will be updated time to time by cron or manual"""

    product_id = fields.Many2one("product.product", "Product")
    warehouse_id = fields.Many2one("stock.warehouse", "Warehouse")
    orderpoint_id = fields.Many2one("stock.warehouse.orderpoint", "Order Point", ondelete='cascade')
    sales_qty = fields.Float("Total Sales Qty")
    total_orders = fields.Integer("Total Sales Order")
    average_daily_sale = fields.Float("Average Daily Sales")
    max_daily_sale_qty = fields.Float("Maximum Daily Sales Qty")
    min_daily_sale_qty = fields.Float("Minimum Daily Sales Qty")
    start_date = fields.Date("Start Date")
    end_date = fields.Date("End Date")
    duration = fields.Integer("Duration In Days")
    actual_sales_qty = fields.Float("Sales Qty")
    actual_sales_return_qty = fields.Float("Sales Return Qty", help="Sales Return Qty")

    def update_product_sales_history(self):
        today = datetime.now().date()
        # UPDATE SALES HISTORY
        start_date = (today - timedelta(days=4)).replace(day=1)
        end_date = today.replace(day=calendar.monthrange(today.year, today.month)[1])
        period_ids = self.env['reorder.fiscalperiod'].search(
            [('fpstartdate', '>=', start_date), ('fpenddate', '<=', end_date)])
        for period in period_ids:
            query = """
                Select * from update_product_sales_history('{}','{}','{}','{}','%s','%s', %s)
            """ % (
                period.fpstartdate.strftime("%Y-%m-%d"), period.fpenddate.strftime("%Y-%m-%d"), self.env.user.id)

            self._cr.execute(query)

        # UPDATE PURCHASE HISTORY
        start_date = today - timedelta(days=4)
        query = """
                Select * from update_product_purchase_history('{}','{}','%s','%s','%s')
            """ % (
            start_date.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"), self.env.user.id)
        self._cr.execute(query)

        # UPDATE IWT HISTORY
        query = """
                Select * from update_product_iwt_history('{}','{}','%s','%s','%s')
            """ % (
            start_date.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"), self.env.user.id)
        self._cr.execute(query)

        self.env['stock.warehouse.orderpoint'].with_context(
            do_not_recalculate_history=True).scheduler_recalculate_data()
        return True
