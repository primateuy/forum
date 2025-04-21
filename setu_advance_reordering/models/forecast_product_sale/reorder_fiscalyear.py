from odoo import fields, models, api, _
from datetime import datetime
from dateutil.relativedelta import relativedelta
from odoo.exceptions import ValidationError, UserError


class ReorderFiscalyear(models.Model):
    _name = 'reorder.fiscalyear'
    _description = "Reorder fiscalyear is used to manage fiscal year for the reordering process"
    _order = "fystartdate desc"

    fystartdate = fields.Date("Start Date")
    fyenddate = fields.Date("End Date")
    code = fields.Char("Code")
    name = fields.Char("Name")
    fp_ids = fields.One2many("reorder.fiscalperiod", "fy_id", "Fiscal Period")

    @api.constrains('fystartdate', 'fyenddate')
    def _check_fiscalyear(self):
        for year in self:
            if year.fyenddate < year.fystartdate:
                raise ValidationError(
                    _('Incorrect fiscal year end date: date must be greater than start date!')
                )
            domain = [('id', '!=', year.id),
                      ('fystartdate', "<", year.fyenddate.strftime("%Y-%m-%d")),
                      ('fyenddate', ">", year.fystartdate.strftime("%Y-%m-%d"))]
            rec = self.search(domain)
            if len(rec) >= 1:
                raise ValidationError(
                    _('Incorrect fiscal year start date or end date: date must not be overlapped')
                )

    def create_monthly_period(self, interval=1):
        period_obj = self.env['reorder.fiscalperiod']
        ds = datetime.strptime(self.fystartdate.strftime('%Y-%m-%d'), '%Y-%m-%d')

        while ds.date() < self.fyenddate:
            de = ds + relativedelta(months=interval, days=-1)

            if de.date() > self.fyenddate:
                de = datetime.strptime(str(self.fyenddate), '%Y-%m-%d')

            period_obj.create({
                'code': ds.strftime('%m/%Y'),
                'fpstartdate': ds.strftime('%Y-%m-%d'),
                'fpenddate': de.strftime('%Y-%m-%d'),
                'fy_id': self.id,
            })
            ds = ds + relativedelta(months=interval)
        return True

    def calculate_actual_sales_for_year(self):
        """
        This method will calculate actual sales year wise.
        """
        for record in self:
            periods = record.fp_ids
            calculative_periods = periods.filtered(lambda x: x.sales_forecast_available)
            if not calculative_periods:
                raise UserError(_('No sales forecast record found for this year to update Actual Sales.'))
            calculative_periods.calculate_actual_sales_for_period()


class ReorderFiscalPeriod(models.Model):
    _name = 'reorder.fiscalperiod'
    _description = "Reorder period is used to manage monthly timeframe for reordering"
    _order = "fpstartdate"
    _rec_name = 'code'

    _sql_constraints = [
        (
            'unique_period_by_fiscalyear', 'UNIQUE(fy_id, fpstartdate)',
            'Only one period allowed for specific time frame')
    ]

    code = fields.Char("Code")
    fy_id = fields.Many2one("reorder.fiscalyear", "Fiscal Year", ondelete="cascade")
    fpstartdate = fields.Date("Start Date")
    fpenddate = fields.Date("End Date")
    sales_forecast_available = fields.Boolean(compute="check_sales_forecast_available")

    def find(self, date):
        period = self.search([('fpstartdate', '<=', date), ('fpenddate', '>=', date)], limit=1)
        return period or False

    def check_sales_forecast_available(self):
        """
        This is a compute method which will check whether sales forecast is available or not for a particular period.
        """
        sales_forecast_obj = self.env['forecast.product.sale']
        for record in self:
            sales_forecast = sales_forecast_obj.search([]).filtered(
                lambda x: x.product_id and x.product_id.active and x.period_id == record)
            if sales_forecast:
                record.sales_forecast_available = True
            else:
                record.sales_forecast_available = False

    def calculate_actual_sales_for_period(self):
        """
        This method will calculate actual sales of product period wise.
        :return: It will return a Boolean.
        """
        sales_forecast_obj = self.env['forecast.product.sale']
        for record in self:
            products = {}
            sales_forecasts = sales_forecast_obj.search([]).filtered(
                lambda x: x.product_id and x.product_id.active and x.period_id == record)
            warehouses = sales_forecasts and set(sales_forecasts.mapped('warehouse_id.id')) or {}
            periods = {record.id}
            if warehouses:
                sales_forecast_obj.update_actual_sales_period_wise(products, warehouses, periods)
        return True
