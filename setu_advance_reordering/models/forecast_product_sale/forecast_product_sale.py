from odoo import fields, models, api
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta


class ForecastProductSale(models.Model):
    _name = 'forecast.product.sale'
    _description = "Product Sales Forecasting"

    @api.depends('period_id', 'forecast_qty')
    def _compute_average_daily_forecast_qty(self):
        for record in self:
            if record and record.period_id:
                difference_days = (record.period_id.fpenddate - record.period_id.fpstartdate).days + 1
                record.average_daily_forecast_qty = record.forecast_qty / difference_days

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            name = self.env['ir.sequence'].next_by_code('forecast.product.sale')
            vals.update({'name': name})
        res = super(ForecastProductSale, self).create(vals_list)
        return res

    name = fields.Char('Name')
    product_id = fields.Many2one('product.product', "Product")
    warehouse_id = fields.Many2one('stock.warehouse', "Warehouse")
    period_id = fields.Many2one('reorder.fiscalperiod', "Fiscal Period")
    forecast_qty = fields.Float("Forecast Quantity")
    previous_forecast_qty = fields.Float("Previous Forecast Quantity")
    previous_period_id = fields.Many2one('reorder.fiscalperiod', "Previous Fiscal Period")
    next_period_id = fields.Many2one('reorder.fiscalperiod', "Next Fiscal Period")
    actual_sale_qty = fields.Float("Actual Sale Quantity")
    average_daily_forecast_qty = fields.Float('Average Daily Forecast Quantity', store=True,
                                              compute='_compute_average_daily_forecast_qty')

    def recalculate_actual_sales(self):
        """
        This method will calculate actual sales of product, warehouse and period wise.
        :return: It will return a successful rainbow man.
        """
        self.calculate_actual_sales()
        return {
            'effect': {
                'fadeout': 'slow',
                'message': 'Actual Sales Calculated Successfully.',
                'img_url': '/web/static/img/smile.svg',
                'type': 'rainbow_man',
            }
        }

    def calculate_actual_sales(self):
        """
        This method will calculate actual sales for product forecast. This method will be called from manually and
        from scheduler.
        """
        sales_forecasts = self
        products = sales_forecasts and set(sales_forecasts.mapped('product_id.id')) or {}
        if not sales_forecasts:
            periods = self.get_last_month_period()
            if periods:
                sales_forecasts = self.search([]).filtered(
                    lambda x: x.product_id and x.product_id.active and x.period_id in periods)
                products = {}
        warehouses = sales_forecasts and set(sales_forecasts.mapped('warehouse_id.id')) or {}
        periods = sales_forecasts and set(sales_forecasts.mapped('period_id.id')) or {}
        if warehouses and periods:
            self.update_actual_sales_period_wise(products, warehouses, periods)
        return True

    def update_actual_sales_period_wise(self, products, warehouses, periods):
        """
        This method will calculate sales actual sales for product forecast period wise.
        :param products: Products list.
        :param warehouses: Warehouses list.
        :param periods: Periods list.
        """
        period_obj = self.env['reorder.fiscalperiod'].sudo()
        for period in periods:
            period = period_obj.browse(period)
            start_date = period.fpstartdate
            end_date = period.fpenddate
            query = """Select * from update_actual_sales('%s','%s',%s,'%s','%s')""" % (
                products, warehouses, period.id, start_date, end_date)
            #         query = """update forecast_product_sale fps
            #     set actual_sale_qty = T.product_qty
            # from (
            #         select D.product_id, D.warehouse_id, sum(D.product_qty) as product_qty from
            #         (
            #             Select S.product_id,S.warehouse_id,S.product_qty as product_qty from get_stock_data(null,'%s',null,'%s','sales','%s','%s')S
            #             UNION ALL
            #             Select SR.product_id,SR.warehouse_id,SR.product_qty * -1 as product_qty from get_stock_data(null,'%s',null,'%s','sales_return','%s','%s')SR
            #         )D group by D.product_id, D.warehouse_id
            # ) T
            # where fps.product_id = T.product_id and fps.warehouse_id = T.warehouse_id and fps.period_id = %s;"""%(products, warehouses, start_date, end_date,products, warehouses, start_date, end_date,period.id)
            #         print(query)
            self._cr.execute(query)

    def get_last_month_period(self):
        """
        This method will calculate last n month reorder fiscal period.
        :return: It will return periods object
        """
        format = '%Y-%m-%d'
        today = datetime.today()
        period_obj = self.env['reorder.fiscalperiod']
        periods = self.env['reorder.fiscalperiod']
        calculation_date = today
        for i in range(0, 1):
            p_month = calculation_date
            last_day_of_prev_month = p_month.replace(day=1) - relativedelta(days=1)
            start_day_of_prev_month = p_month.replace(day=1) - relativedelta(days=last_day_of_prev_month.day)
            start_day_of_prev_month_str = start_day_of_prev_month.strftime(format)
            periods += period_obj.search([('fpstartdate', '<=', start_day_of_prev_month_str),
                                          ('fpenddate', '>=', start_day_of_prev_month_str)])
            calculation_date = start_day_of_prev_month

        today_str = today.strftime(format)
        current_period = self.env['reorder.fiscalperiod'].search([('fpstartdate', '<=', today_str),
                                                                  ('fpenddate', '>=', today_str)])
        if current_period and current_period not in periods:
            periods += current_period
        return periods
