from odoo import fields, models, api, _, registry, SUPERUSER_ID
from odoo.exceptions import ValidationError
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from statistics import mean
import logging

_logger = logging.getLogger(__name__)


class StockWarehouseOrderpoint(models.Model):
    _name = "stock.warehouse.orderpoint"
    _inherit = ['stock.warehouse.orderpoint', 'mail.thread', 'mail.activity.mixin']

    def _default_avg_sale_calculation_base(self):
        para = self.env['ir.config_parameter'].sudo().search(
            [('key', '=', 'setu_advance_reordering.average_sale_calculation_base')])
        return para and para.value or 'quarterly_average'

    product_id = fields.Many2one(
        'product.product', 'Product',
        domain="[('type', '=', 'product'), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        ondelete='cascade', required=True, check_company=True, change_default=True)

    suggested_min_qty = fields.Integer("Suggested Min Qty")
    suggested_max_qty = fields.Integer("Suggested Max Qty")
    ads_qty = fields.Float("Average Daily Sales", change_default=True, )
    max_daily_sale_qty = fields.Float("Maximum Daily Sales")
    max_lead_time = fields.Integer("Maximum Lead Time")
    avg_lead_time = fields.Integer("Average Lead Time")
    product_sales_history_ids = fields.One2many("product.sales.history", "orderpoint_id", "Sales History")
    product_purchase_history_ids = fields.One2many("product.purchase.history", "orderpoint_id", "Purchase History")
    product_warehouse_movement_history_ids = fields.One2many("product.iwt.history", "orderpoint_id",
                                                             string="Warehouse movement History")
    safety_stock = fields.Float("Safety Stock", change_default=True, )
    buffer_days = fields.Integer("Buffer Days", help="""
        If you will add buffer days then system will add "buffer days * average daily sales" in to the maximum ordered quantity calculation
    """, change_default=True, )
    suggested_safety_stock = fields.Float("Suggested Safety Stock", change_default=True, )
    vendor_selection_strategy = fields.Selection([('NA', 'Not Applicable'),
                                                  ("cheapest", "Cheapest vendor"),
                                                  ("quickest", "Quickest vendor"),
                                                  ("specific_vendor", "Specific vendor")],
                                                 string="Vendor selection strategy", default="NA",
                                                 help="""This field is useful when purchase order is created from order points 
                                                   that time system checks about the vendor which is suitable for placing an order 
                                                   according to need. Whether quickest vendor, cheapest vendor or specific vendor is suitable 
                                                   for the product"""
                                                 )
    partner_id = fields.Many2one("res.partner", "Vendor")
    average_sale_calculation_base = fields.Selection([
        ("monthly_average", "Past 1 Month"),
        ("bi_monthly_average", "Past 2 Month"),
        ("quarterly_average", "Past 3 Month"),
        ("onetwenty_days_average", "Past 4 Month"),
        ("six_month_averagy", "Past 6 Month"),
        ("annual_average", "Past 12 Month")],
        default=_default_avg_sale_calculation_base, change_default=True, string="Get Average Sales From")
    consider_current_period_sales = fields.Boolean('Consider Current Period Sales', help='consider current period '
                                                                                         'sales in the sales history'
                                                                                         ' calculation', default=True)
    document_creation_option = fields.Selection([('ict', 'Inter Company Transfer'),
                                                 ('iwt', 'Inter Warehouse Transfer'),
                                                 ('po', 'Purchase Order'),
                                                 ('od_default', 'Odoo Default'), ], string="Create",
                                                change_default=True,
                                                default='od_default',
                                                help="Inter Company Transfer(ICT) - System will create an Inter "
                                                     "Company Transfer.\nInter Warehouse Transfer(IWT) - System will "
                                                     "create an Inter Warehouse Transfer.\nPurchase Order - System "
                                                     "will create a Purchase Order.\n\nNote - ICT and IWT will be "
                                                     "worked as per the configuration of Inter Company Channel.")
    add_purchase_in_lead_calc = fields.Boolean("Purchase", default=True)
    add_iwt_in_lead_calc = fields.Boolean("IWT", default=False)
    partner_ids = fields.Many2many('res.partner', string="Partners", compute="compute_partner_ids")

    @api.depends('product_id')
    def compute_partner_ids(self):
        for record in self:
            if record.product_id:
                record.partner_ids = False
                partner_ids = record.product_id.seller_ids.mapped("partner_id").ids
                record.partner_ids = partner_ids
            else:
                record.partner_ids = False

    @api.constrains('max_daily_sale_qty', 'max_lead_time')
    def _check_leadtime_ads(self):
        for orderpoint in self:
            if orderpoint.max_daily_sale_qty < orderpoint.ads_qty:
                raise ValidationError(
                    _('Incorrect Max daily sales qty: Maximum daily sales must be greater than average daily sales!')
                )

            if orderpoint.max_lead_time < orderpoint.avg_lead_time:
                raise ValidationError(
                    _('Incorrect Max lead time: Maximum lead time must be greater than average lead time!')
                )

    def _calculate_lead_time(self):
        calc_base_on = self.env['advance.reordering.settings'].search([]).purchase_lead_calc_base_on
        if calc_base_on != 'static_lead_time':
            for orderpoint_id in self.ids:
                orderpoint = self.browse(orderpoint_id)
                product_history = []
                if orderpoint.add_purchase_in_lead_calc:
                    if calc_base_on == 'vendor_lead_time':
                        product_history += orderpoint.product_id.seller_ids.mapped('delay')
                    else:
                        product_history += orderpoint.product_purchase_history_ids.mapped('lead_time')

                if orderpoint.add_iwt_in_lead_calc:
                    product_history += orderpoint.product_warehouse_movement_history_ids.mapped('lead_time')

                avg_lead_time = product_history and round(mean(product_history)) or 1
                calc_method = self.env['advance.reordering.settings'].search([]).max_lead_days_calc_method
                if calc_method == 'avg_extra_percentage':
                    extra_percentage = float(
                        self.env['advance.reordering.settings'].search([]).extra_lead_percentage or 0.0) + 1.0
                    max_lead_time = avg_lead_time and round(avg_lead_time * extra_percentage) or 1
                else:
                    max_lead_time = product_history and round(max(product_history)) or 1

                orderpoint.write({
                    'avg_lead_time': avg_lead_time,
                    'max_lead_time': max_lead_time
                })
        return True

    def get_date(self, days):
        return (datetime.today() - relativedelta(days=days)).date()

    def get_sales_data(self, start_date, end_date):
        filtered_data = self.product_sales_history_ids.filtered(
            lambda x: start_date <= x.start_date <= end_date)
        number_of_sales_days = (end_date - start_date).days + 1
        filtered_avg_data = sum(filtered_data.mapped('sales_qty')) if sum(filtered_data.mapped('sales_qty')) > 0 else 0
        filtered_max_data = filtered_data.mapped('max_daily_sale_qty')
        avg_sale = filtered_avg_data and filtered_avg_data / number_of_sales_days or 0.0
        calc_method = self.env['advance.reordering.settings'].search([]).max_sales_calc_method
        if calc_method == 'avg_extra_percentage':
            extra_percentage = float(self.env['advance.reordering.settings'].search([]).extra_sales_percentage) + 1.0
            max_sale = avg_sale and avg_sale * extra_percentage or 0.0
        else:
            max_sale = filtered_max_data and max(filtered_max_data) or 0.0
        return avg_sale, max_sale

    def calculate_sales_average_max(self):
        for orderpoint_id in self.ids:
            orderpoint = self.browse(orderpoint_id)
            orderpoint.onchange_avg_sale_lead_time()
            orderpoint.onchange_safety_stock()
        return True

    def update_product_purchase_history(self):
        products = set(self.mapped('product_id').ids)
        warehouses = set(self.mapped('warehouse_id').ids)
        query = """
            Select * from update_product_purchase_history('%s','%s','%s','%s','%s')
        """ % (products, warehouses, self.get_date(365).strftime("%Y-%m-%d"),
               datetime.today().strftime("%Y-%m-%d"), self.env.user.id)
        self._cr.execute(query)
        return True

    def update_product_sales_history(self):
        products = set(self.mapped('product_id').ids)
        warehouses = set(self.mapped('warehouse_id').ids)
        start_date = self.get_date(365).replace(day=1).strftime("%Y-%m-%d")
        end_date = datetime.today().strftime("%Y-%m-%d")
        period_ids = self.env['reorder.fiscalperiod'].search(
            [('fpstartdate', '>=', start_date), ('fpstartdate', '<=', end_date)])
        for period in period_ids:
            query = """
                Select * from update_product_sales_history('{}','%s','{}','%s','%s','%s', '%s')
            """ % (products, warehouses, period.fpstartdate.strftime("%Y-%m-%d"),
                   period.fpenddate.strftime("%Y-%m-%d"), self.env.user.id)
            self._cr.execute(query)
        return True

    def update_product_iwt_history(self):
        products = set(self.mapped('product_id').ids)
        warehouses = set(self.mapped('warehouse_id').ids)
        query = """
                    Select * from update_product_iwt_history('%s','%s','%s','%s','%s')
                """ % (products, warehouses, self.get_date(365).strftime("%Y-%m-%d"),
                       datetime.today().strftime("%Y-%m-%d"), self.env.user.id)
        self._cr.execute(query)
        return True

    @api.onchange('document_creation_option')
    def onchange_document_creation_option(self):
        for record in self:
            document_creation_option = record.document_creation_option
            if document_creation_option and document_creation_option != 'po':
                record.vendor_selection_strategy = ''

    # @api.onchange('product_id')
    # def onchange_product_id(self):
    # Replaced with compute_partner_ids
    #     if self.product_id:
    #         partner_ids = self.product_id.seller_ids.mapped("partner_id").ids
    #         return {'domain': {'partner_id': [('id', 'in', partner_ids)]}}

    @api.onchange('average_sale_calculation_base')
    def onchange_average_sale_calculation_base(self):
        ads_qty = max_daily_sale_qty = 0.0
        if self.average_sale_calculation_base:
            if self.average_sale_calculation_base == "monthly_average":
                ads_qty, max_daily_sale_qty = self.get_avg_and_max_sales(1)
            elif self.average_sale_calculation_base == "bi_monthly_average":
                ads_qty, max_daily_sale_qty = self.get_avg_and_max_sales(2)
            elif self.average_sale_calculation_base == "quarterly_average":
                ads_qty, max_daily_sale_qty = self.get_avg_and_max_sales(3)
            elif self.average_sale_calculation_base == "onetwenty_days_average":
                ads_qty, max_daily_sale_qty = self.get_avg_and_max_sales(4)
            elif self.average_sale_calculation_base == "six_month_averagy":
                ads_qty, max_daily_sale_qty = self.get_avg_and_max_sales(6)
            elif self.average_sale_calculation_base == "annual_average":
                ads_qty, max_daily_sale_qty = self.get_avg_and_max_sales(12)

        self.ads_qty = ads_qty
        self.max_daily_sale_qty = max_daily_sale_qty

    def get_avg_and_max_sales(self, months):
        """
        This method will calculate average and max sales of a period.
        :param days: Number of days.
        :return: It will return average and max sales of a period.
        """
        if self.consider_current_period_sales:
            end_date = datetime.now().date()
        else:
            end_date = date.today().replace(day=1) - relativedelta(days=1)
        days_start = date.today().replace(day=1) - relativedelta(months=months)
        # days_start = self.get_date(days)
        days_avg_sales, days_max_sales = self.get_sales_data(days_start, end_date)
        return days_avg_sales, days_max_sales

    # @api.onchange('partner_id')
    # def onchange_partner_id(self):
    #     lead_days = 1
    #     if self.partner_id and self.product_id:
    #         supplier_info = self.product_id.seller_ids.filtered(lambda supplier: supplier.name == self.partner_id)
    #         print(supplier_info)
    #         if supplier_info:
    #             lead_days = supplier_info[0].delay
    #             print(lead_days)
    #     self.lead_days = lead_days

    # @api.depends('max_daily_sale_qty', 'ads_qty', 'max_lead_time', 'avg_lead_time')
    @api.onchange('max_daily_sale_qty', 'ads_qty', 'max_lead_time', 'avg_lead_time')
    def onchange_avg_sale_lead_time(self):
        self.suggested_safety_stock = (self.max_lead_time - self.avg_lead_time) * self.ads_qty
        # self.suggested_safety_stock = round(((self.max_daily_sale_qty * self.max_lead_time) - (self.ads_qty * self.avg_lead_time)),0) or 0

    # @api.depends('suggested_safety_stock')
    @api.onchange('suggested_safety_stock')
    def onchange_safety_stock(self):
        self.suggested_min_qty = ((self.avg_lead_time * self.ads_qty) + self.suggested_safety_stock) or 0
        self.suggested_max_qty = (self.suggested_min_qty + (self.buffer_days * self.ads_qty)) or 0

    @api.onchange('product_min_qty', 'buffer_days', 'safety_stock', 'ads_qty')
    def onchange_min_stock_buffer_days(self):
        self.product_max_qty = round((self.product_min_qty + self.safety_stock + (self.buffer_days * self.ads_qty)),
                                     0) or 0
        self.suggested_max_qty = (self.suggested_min_qty + (self.buffer_days * self.ads_qty)) or 0
        # self.suggested_max_qty = ((self.avg_lead_time * self.ads_qty)+ self.suggested_safety_stock + (self.buffer_days * self.ads_qty) ) or 0

    def update_order_point_data(self):
        query = f"""update stock_warehouse_orderpoint as swo
                        set product_min_qty =tmp.suggested_min_qty,
                            safety_stock = tmp.suggested_safety_stock,
                            product_max_qty = tmp.suggested_max_qty
                        from(
                                select 	wo.id,
                                         coalesce(wo.suggested_min_qty,0) AS suggested_min_qty,
                                        coalesce(wo.suggested_safety_stock,0) AS suggested_safety_stock,
                                        coalesce(wo.suggested_max_qty,0) AS suggested_max_qty
                                from stock_warehouse_orderpoint wo
                                     join product_product prod on prod.id = wo.product_id
                                where prod.active = true
                                      and prod.update_orderpoint = true
                                      and wo.id in {tuple(self.ids) if len(self.ids) > 1 else '(' + str(self.id) + ')'}
                        )tmp
                        where swo.id = tmp.id"""
        self._cr.execute(query)

    def reset_all_data(self):
        vals = {
            'ads_qty': 0,
            'max_daily_sale_qty': 0,
        }
        calc_base_on = self.env['advance.reordering.settings'].search([]).purchase_lead_calc_base_on
        if calc_base_on != 'static_lead_time':
            vals.update({'max_lead_time': 0,
                         'avg_lead_time': 0})
        self.write(vals)

    @api.model
    def scheduler_recalculate_data(self):
        """
        This method will recalculate order point calculation whenever its scheduler will run.
        :return:
        """
        orderpoints = self.env['stock.warehouse.orderpoint'].search([('product_id.type', '=', 'product')])
        do_not_recalculate_history = self._context.get('do_not_recalculate_history', False)
        if orderpoints and not do_not_recalculate_history:
            orderpoints.update_product_purchase_history()
            orderpoints.update_product_sales_history()
            orderpoints.update_product_iwt_history()
            self._cr.commit()
        for orderpoint in orderpoints:
            orderpoint._calculate_lead_time()
            orderpoint.calculate_sales_average_max()
            orderpoint.onchange_average_sale_calculation_base()
            orderpoint.onchange_safety_stock()
            orderpoint.onchange_avg_sale_lead_time()
            orderpoint.onchange_safety_stock()
        if orderpoints:
            self._cr.commit()
            orderpoints.update_order_point_data()
        return True

    def recalculate_data(self):
        history_context = self._context.get('already_calculated_history', False)
        self.reset_all_data()
        if not history_context:
            self.update_product_purchase_history()
            self.update_product_iwt_history()
            self.update_product_sales_history()
        self._calculate_lead_time()
        self.calculate_sales_average_max()
        self.onchange_average_sale_calculation_base()
        self.onchange_safety_stock()
        self.onchange_avg_sale_lead_time()
        self.onchange_safety_stock()

    def create_schedule_activity(self, values):
        """
        This method will create activity for order point.
        :param values: Dictionary of activity values.
        :return: It will return activity object.
        """
        activity_obj = self.env['mail.activity']
        document = "ICT" if self.document_creation_option == 'ict' else "IWT"
        message = "<b>Can't create %s for this orderpoint, because %s channel not found for this company. Create " \
                  "%s manually.</b>" % (document, document, document)
        model = self.env['ir.model'].sudo().search([('model', '=', 'stock.warehouse.orderpoint')], limit=1)
        domain = [('automated', '=', True), ('date_deadline', '=', datetime.today().strftime('%Y-%m-%d')),
                  ('note', '=', message), ('res_model_id', '=', model.id), ('res_id', '=', self.id)]
        activity = activity_obj.sudo().search(domain)
        if activity:
            return activity
        orderpoint_activity_vals = self.prepare_orderpoint_activity_vals()
        orderpoint_activity_vals.update(values)
        activity = activity_obj.create(orderpoint_activity_vals)
        return activity

    def prepare_orderpoint_activity_vals(self):
        """
        This method will prepare activity vals for order point.
        :return:
        """
        activity_type = self.env.ref('mail.mail_activity_data_todo')
        model = self.env['ir.model'].sudo().search([('model', '=', 'stock.warehouse.orderpoint')], limit=1)
        return {
            'activity_type_id': activity_type and activity_type.id,
            'summary': activity_type.summary,
            'automated': True,
            'note': activity_type.default_description,
            'date_deadline': datetime.today().strftime('%Y-%m-%d'),
            'res_model_id': model.id,
            'res_id': self.id,
            'user_id': self.env.user.id
        }
