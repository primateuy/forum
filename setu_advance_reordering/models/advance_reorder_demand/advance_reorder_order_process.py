from lxml import etree
from datetime import datetime
from dateutil import relativedelta
from odoo import fields, models, api, _
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from odoo.exceptions import UserError
from odoo.exceptions import ValidationError


class AdvanceReorderOrderProcess(models.Model):
    _name = 'advance.reorder.orderprocess'
    _inherit = ['mail.thread']
    _description = "Advance reorder by demand generation"
    _order = 'id desc'

    # def _compute_is_request_approval(self):
    #     approval_system_for_reorder = self.env['ir.config_parameter'].sudo(). \
    #         get_param('setu_advance_reordering.approval_system_for_reorder')
    #     for record in self:
    #         record.is_request_approval = approval_system_for_reorder or False

    def _compute_count_purchase_order(self):
        for record in self:
            record.purchase_count = len(record.purchase_ids)

    def _compute_count_replenishment(self):
        for record in self:
            record.replenishment_count = len(record.replenishment_ids)

    def _default_volume_uom_name(self):
        volume_uom = self.env['product.template']._get_volume_uom_id_from_ir_config_parameter()
        return volume_uom and volume_uom.name or ''

    name = fields.Char("Name", help="Reorder number")
    reorder_date = fields.Datetime('Reorder date', help="Reorder date", default=datetime.now())
    user_id = fields.Many2one('res.users', string="Responsible", default=lambda self: self.env.user,
                              help="Responsible user")
    state = fields.Selection([('draft', 'Draft'),
                              ('inprogress', 'InProgress'),
                              ('verified', 'Verified'),
                              ('waiting_for_approval', 'Waiting for Approval'),
                              ('approved', 'Approved'),
                              ('reject', 'Rejected'),
                              ('done', 'Done'),
                              ('no_data', 'No Data'),
                              ('cancel', 'Cancel')],
                             default="draft", string="Status",
                             help="To identify process status", tracking=True)
    approve_id = fields.Many2one('res.users', string="Approver", help="Set name of approver",
                                 domain=lambda self: [('groups_id', 'in',
                                                       self.env.ref(
                                                           'setu_advance_reordering.group_advance_reordering_approved').ids)])
    vendor_id = fields.Many2one('res.partner', string="Vendor",
                                help="Set the vendor to whom you want to place an order")
    currency_id = fields.Many2one('res.currency', string="Currency", related='vendor_id.currency_id')
    minimum_reorder_amount = fields.Monetary('Min order amount', related='vendor_id.minimum_reorder_amount',
                                             help="Minimum reorder amount defined by vendors")
    reorder_amount = fields.Monetary(string='Reorder amount',
                                     help="Reorder amount will be calculated from the generated demands", copy=False)
    product_ids = fields.Many2many("product.product", string="Products")
    buffer_security_days = fields.Integer('Coverage days',
                                          help="Place order for next x days, system will generate demands for next x"
                                               " days after order transit time")
    generate_demand_with = fields.Selection([('history_sales', 'History Sales'),
                                             ('forecast_sales', 'Forecast Sales')],
                                            string="Demand calculation by",
                                            help="Demand generate based on past sales or forecasted sales",
                                            default='history_sales')
    sales_start_date = fields.Date("From date")
    sales_end_date = fields.Date("End date")
    reorder_demand_growth = fields.Float('Expected growth (%)',
                                         help="Add percentage value if you want to calculate demand with growth")
    forecast_period_ids = fields.Many2many("reorder.fiscalperiod", string="Forecast periods")

    # place_order_in_cartoon_qty = fields.Boolean('Place Order in Cartoon Quantity',
    #                                             help="Set true if Order Quantity in Bulk")
    purchase_ids = fields.One2many('purchase.order', 'reorder_process_id', string='Purchase orders')
    purchase_count = fields.Integer('Purchase order count', compute="_compute_count_purchase_order")
    # is_request_approval = fields.Boolean('Is approval required?', compute='_compute_is_request_approval',
    #                                      help="Set if approval required")
    config_ids = fields.One2many('advance.reorder.orderprocess.config', 'reorder_process_id',
                                 string='Reorder configuration', help="Reorder configuration")
    line_ids = fields.One2many('advance.reorder.orderprocess.line', 'reorder_process_id', string='Reorder lines')
    summary_ids = fields.One2many('advance.reorder.orderprocess.summary', 'reorder_process_id',
                                  string='Advance Reorder Process Summary',
                                  help="Reorder summary which will be used to create purchase order")
    non_forecast_ids = fields.One2many('advance.reorder.non.product.forecast', 'reorder_process_id',
                                       string='Advance Reorder Non Product Forecast',
                                       help="Add value which forecast value not found")
    is_reorder_line_pending = fields.Boolean("Is Reorder Line Pending")
    reorder_total_volume = fields.Float("Reorder Total Volume", copy=False)
    volume_uom_name = fields.Char('Volume Unit of Measure', default=_default_volume_uom_name)
    vendor_rule = fields.Selection(related='vendor_id.vendor_rule', string='Vendor Rule')
    reorder_classification_ids = fields.One2many('reorder.summary.classification', 'reorder_process_id',
                                                 string='Reorder Classification')
    reorder_stock_movement_ids = fields.One2many('reorder.stock.movement.report', 'reorder_process_id',
                                                 string='Reorder Stock Movement')

    reorder_planner_id = fields.Many2one('advance.reorder.planner', string='Reorder Planner')
    replenishment_ids = fields.One2many('advance.procurement.process', 'reorder_id', string='Replenishment Order')
    replenishment_count = fields.Integer('Replenishment count', compute="_compute_count_replenishment")
    computed_product_ids = fields.Many2many('product.product', 'computed_product_order_process_rel', string="Products",
                                            compute="compute_product_ids")

    # def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
    #     res = super(AdvanceReorderOrderProcess, self).fields_view_get(view_id=view_id, view_type=view_type,
    #                                                                   toolbar=toolbar, submenu=submenu)
    #     if view_type == 'form':
    #         approval_system_for_reorder = self.env['ir.config_parameter'].sudo(). \
    #             get_param('setu_advance_reordering.approval_system_for_reorder')
    #         doc = etree.XML(res['arch'])
    #         for node in doc.xpath("//field[@name='state']"):
    #             if approval_system_for_reorder:
    #                 node.set("statusbar_visible",
    #                          "draft,inprogress,verified,waiting_for_approval,approved,reject,done,cancel")
    #             else:
    #                 node.set("statusbar_visible", "draft,inprogress,verified,done,cancel")
    #         res['arch'] = etree.tostring(doc)
    #     return res

    # @api.onchange('vendor_id')
    # def onchange_vendor_id(self):
    #   Replaced with compute_product_ids
    #     vendor = self.vendor_id
    #     all_products = self.env['product.product'].sudo().search([])
    #     if not vendor:
    #         return {'domain': {
    #             'product_ids': [('id', 'in', all_products.ids), ('active', '!=', False), ('purchase_ok', '!=', False)]}}
    #
    #     all_products = self.env['product.supplierinfo'].sudo().search([('partner_id', '=', vendor.id)]).mapped(
    #         'product_tmpl_id').mapped('product_variant_ids')
    #
    #     return {'domain': {
    #         'product_ids': [('id', 'in', all_products.ids), ('active', '!=', False), ('purchase_ok', '!=', False)]}}

    @api.depends('vendor_id')
    def compute_product_ids(self):
        for record in self:
            vendor = record.vendor_id
            if not vendor:
                all_products = self.env['product.product'].sudo().search(
                    [('purchase_ok', '!=', False),('company_id', 'in', [False, self.env.company.id])])
            else:
                all_products = self.env['product.supplierinfo'].sudo().search([('partner_id', '=', vendor.id),('company_id', 'in', [False, self.env.company.id])]).mapped(
                    'product_tmpl_id').mapped('product_variant_ids').filtered(lambda x: x.purchase_ok != False)
            record.sudo().computed_product_ids = all_products

    @api.onchange('buffer_security_days')
    def onchange_buffer_security_days(self):
        days = self.buffer_security_days - 1 if self.buffer_security_days > 0.0 \
            else self.buffer_security_days
        for config in self.config_ids:
            config.advance_stock_start_date = (config.order_arrival_date +
                                               relativedelta.relativedelta(days=1)).strftime("%Y-%m-%d")
            config.advance_stock_end_date = (config.advance_stock_start_date +
                                             relativedelta.relativedelta(days=days)).strftime("%Y-%m-%d")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            name = self.env['ir.sequence'].next_by_code('advance.reorder.orderprocess')
            vals.update({'name': name})
        res = super(AdvanceReorderOrderProcess, self).create(vals_list)
        return res

    def unlink(self):
        for record in self:
            if record.state not in ['draft', 'inprogress']:
                raise UserError("In order to delete advance reorder, you must reset to draft or cancel it first.")
        return super(AdvanceReorderOrderProcess, self).unlink()

    # def action_request_for_approval(self):
    #     self.write({'state': 'waiting_for_approval'})
    #     return True

    # def action_approve_reorder_process(self):
    #     self.write({'state': 'approved'})
    #     return True
    #
    # def action_reject_reorder_process(self):
    #     self.write({'state': 'reject'})
    #     return True

    def check_configuration_product(self):
        if not self.product_ids or not self.config_ids:
            raise UserError('Before validate please add warehouse group in configuration tab or select product')

    def get_history_sales(self, products, warehouses, start_date, end_date):
        start_date = start_date.strftime("%Y-%m-%d")
        end_date = end_date and end_date.strftime("%Y-%m-%d")
        query = """Select product_id,product_name,sum(sales) as sales,sum(sales_return) as sales_return,
                sum(total_sales) as total_sales,sum(ads) as ads from 
                get_products_sales_warehouse_group_wise('%s','%s','%s','%s','%s','%s')
                group by product_id,product_name
        """ % ('{}', products, '{}', warehouses, start_date, end_date)
        self._cr.execute(query)
        return self._cr.dictfetchall()

    def get_forecast_sales(self, products, warehouses, config):
        non_forecast_query = """SELECT * FROM get_reorder_non_product_forecast('%s','%s','%s','%s', null,'%s','%s')""" \
                             % (self.env.user.id, str(config.order_date), str(config.advance_stock_end_date),
                                self.id, products, warehouses)
        self._cr.execute(non_forecast_query)
        non_forecast_data = self._cr.dictfetchall()
        is_forecast = non_forecast_data[0].get('get_reorder_non_product_forecast')
        is_forecast and self.write({'is_reorder_line_pending': True})
        query = """Select * from get_reorder_forecast_data('%s','%s','%s','%s','%s','%s')""" \
                % (str(config.order_date), str(config.order_arrival_date),
                   str(config.advance_stock_start_date),
                   str(config.advance_stock_end_date), products, warehouses)
        self._cr.execute(query)
        return self._cr.dictfetchall()

    def get_sales_data(self, config):
        products = self.product_ids and set(self.product_ids.ids) or {}
        warehouses = config.warehouse_group_id and set(config.warehouse_group_id.warehouse_ids.ids) or {}
        if self.generate_demand_with == 'history_sales':
            return self.get_history_sales(products, warehouses, self.sales_start_date, self.sales_end_date)
        else:
            return self.get_forecast_sales(products, warehouses, config)

    def get_stock_move(self, product, config):
        stock_location_ids = config.warehouse_group_id.warehouse_ids.mapped('lot_stock_id').ids
        stock_move_ids = self.env['stock.move'].search([('product_id', '=', product.id),
                                                        ('state', 'not in', ['draft', 'cancel', 'done']),
                                                        ('location_dest_id', 'in', stock_location_ids)]).ids
        return stock_move_ids

    def prepare_reorder_line_vals(self, config, sales_data, generate_demand_with):
        vals = []
        reorder_demand_growth = self.reorder_demand_growth and self.reorder_demand_growth / 100 or 0.0
        reorder_rounding_method = self.env['advance.reordering.settings'].search([]).reorder_rounding_method
        reorder_round_quantity = int(self.env['advance.reordering.settings'].search([]).reorder_round_quantity)

        for data in sales_data:
            product = self.env['product.product'].browse(data.get('product_id'))
            wh_available = sum([product.with_context({'warehouse': wh.id}).virtual_available for wh in
                                config.warehouse_group_id.warehouse_ids])
            wh_outgoing = sum([product.with_context({'warehouse': wh.id}).outgoing_qty for wh in
                               config.warehouse_group_id.warehouse_ids])
            wh_incoming = sum([product.with_context({'warehouse': wh.id}).incoming_qty for wh in
                               config.warehouse_group_id.warehouse_ids])
            net_on_hand = wh_available  # - wh_outgoing
            if net_on_hand < 0:
                net_on_hand = 0
            ads = data.get('ads', 0.0)

            if generate_demand_with == 'history_sales':
                ads = reorder_demand_growth and ads + (ads * reorder_demand_growth) or ads
                lead_days_demand = round(ads * config.vendor_lead_days, 2)
                expected_sales = self.buffer_security_days * ads
            else:
                lead_days_demand = data.get('lead_days_demand_stock', 0.0)
                expected_sales = data.get('expected_sales_stock', 0.0)

            transit_demand = lead_days_demand if net_on_hand > lead_days_demand else net_on_hand
            stock_after_transit = net_on_hand - transit_demand

            demand_qty = round(0 if stock_after_transit > expected_sales
                               else expected_sales - stock_after_transit, 2)
            demand_adjustment_qty = demand_qty

            if reorder_round_quantity and not demand_adjustment_qty % reorder_round_quantity == 0.0:
                if reorder_rounding_method == 'round_up' and not demand_qty == 0.0:
                    # c2 = (a + b) - (a % b);
                    demand_adjustment_qty = (demand_qty + reorder_round_quantity) - (
                            demand_qty % reorder_round_quantity)
                elif reorder_rounding_method == 'round_down' and not demand_qty == 0.0:
                    # c1 = a - (a % b);
                    demand_adjustment_qty = demand_qty - (demand_qty % reorder_round_quantity)

            stock_move_ids = self.get_stock_move(product, config)

            reorder_line_vals = {
                'warehouse_group_id': config.warehouse_group_id.id,
                'reorder_process_id': self.id,
                'product_id': product.id,
                'available_stock': net_on_hand,
                'average_daily_sale': ads,
                'transit_time_sales': transit_demand,
                'stock_after_transit': stock_after_transit,
                'expected_sales': expected_sales,
                'demanded_qty': demand_qty,
                'incoming_qty': wh_incoming,
                'demand_adjustment_qty': round(demand_adjustment_qty, 0),
                # 'demand_adjustment_qty': round(demand_qty, 0),
                'stock_move_ids': [(6, 0, stock_move_ids)],
            }

            line_id = self.line_ids.filtered(lambda x: x.product_id == product and
                                                       x.warehouse_group_id == config.warehouse_group_id)
            if line_id:
                line_id.write(reorder_line_vals)
                continue
            vals.append((0, 0, reorder_line_vals))
        return vals

    def action_reorder_confirm(self):
        self.check_configuration_product()
        vals = []
        reorder_vals = {}
        reorder_classification_vals = []
        stock_movement_vals = []
        for config in self.config_ids:
            sales_data = self.get_sales_data(config)
            vals.extend(self.prepare_reorder_line_vals(config, sales_data, self.generate_demand_with))
        # if self.generate_demand_with == 'history_sales':
        #     products = self.product_ids and set(self.product_ids.ids) or {}
        #     warehouses = self.config_ids and set(list(set(self.config_ids.mapped('warehouse_group_id')
        #                                                   .mapped('warehouse_ids').ids))) or {}
        #     reorder_classification_vals = self.env['reorder.summary.classification'].\
        #         prepare_reorder_classification(products, warehouses, self.sales_start_date,
        #                                         self.sales_end_date, self.reorder_classification_ids)
        #     stock_movement_vals = self.env['reorder.stock.movement.report'].\
        #         prepare_stock_movement_report(products, warehouses, self.sales_start_date,
        #                                     self.sales_end_date, self.reorder_stock_movement_ids)
        if not self.state == 'inprogress':
            reorder_vals = {'state': 'no_data'}
        vals and reorder_vals.update({'line_ids': vals, 'state': 'inprogress'})
        self.write(reorder_vals)
        # ,'reorder_classification_ids': reorder_classification_vals,
        # 'reorder_stock_movement_ids': stock_movement_vals})
        return True

    def action_recalculate_demand(self):
        self.action_reorder_confirm()
        if not self.non_forecast_ids and self.is_reorder_line_pending:
            self.write({'is_reorder_line_pending': False})
        return True

    def action_reorder_create_forecast_sale(self, non_forecast_ids=False):
        forecast_sale_obj = self.env['forecast.product.sale']
        if not non_forecast_ids:
            non_forecast_ids = self.non_forecast_ids.filtered(lambda x: x.forecast_qty)
        if not non_forecast_ids:
            raise ValidationError(_("Quantities in Missing Forecasted sales lines should be greater then 0."))
        for non_forecast_sale in non_forecast_ids:
            forecast_sale_obj.create({
                'product_id': non_forecast_sale.product_id.id,
                'warehouse_id': non_forecast_sale.warehouse_id.id,
                'period_id': non_forecast_sale.period_id.id,
                'forecast_qty': non_forecast_sale.forecast_qty
            })
        non_forecast_ids.unlink()
        return True

    def action_reorder_import_forecast_sale(self):
        self.ensure_one()
        action = self.env.ref('setu_advance_reordering.action_sale_forecast_auto_import_wizard').sudo().read()[0]
        action.update({'context': {'reorder_import_foreacast': True}})
        return action

    def prepare_reorder_summary_vals(self):
        summary_vals = []
        reorder_total_volume = []
        reorder_total_amount = []
        for product in self.product_ids:
            lines = self.line_ids.filtered(lambda x: x.product_id.id == product.id and x.demand_adjustment_qty > 0.0)
            if lines:
                total_demand = sum(lines.mapped('demand_adjustment_qty'))
                for line_id in lines:
                    line_id.wh_sharing_percentage = round((line_id.demand_adjustment_qty / total_demand) * 100) or 0.0

                warehouse_id = lines[0].warehouse_group_id and lines[0].warehouse_group_id[0].warehouse_ids
                warehouse_id = warehouse_id and warehouse_id[0] or False

                company_id = warehouse_id and warehouse_id.company_id or False

                if company_id:
                    ps_info = product.seller_ids.filtered(lambda
                                                              x: x.partner_id.id == self.vendor_id.id and x.company_id == company_id and x.currency_id == company_id.currency_id)
                else:
                    ps_info = product.seller_ids.filtered(lambda x: x.partner_id.id == self.vendor_id.id)

                ps_info_have_min_qty = ps_info.filtered(lambda x: x.reorder_minimum_quantity > 0)
                if ps_info_have_min_qty:
                    ps_info_have_min_qty = ps_info_have_min_qty.filtered(
                        lambda x: x.reorder_minimum_quantity <= total_demand).sorted(
                        key=lambda x: x.reorder_minimum_quantity, reverse=True)
                    if ps_info_have_min_qty:
                        ps_info = ps_info_have_min_qty[0]

                ps_info = ps_info and len(ps_info) > 1 and ps_info[0] or ps_info

                order_qty = total_demand
                if total_demand < ps_info.reorder_minimum_quantity:
                    order_qty = ps_info.reorder_minimum_quantity

                weight = product.weight
                if weight <= 0:
                    weight = 1
                total_volume = order_qty * product.volume * weight
                reorder_total_volume.append(total_volume)
                reorder_total_amount.append(round(order_qty) * ps_info.price)
                order_qty_in_purchase_uom = round(
                    product.uom_id._compute_quantity(qty=order_qty, to_unit=product.uom_po_id))
                summary_vals.append((0, 0, {'product_id': product.id,
                                            'demanded_qty': total_demand,
                                            'vendor_moq': ps_info.reorder_minimum_quantity,
                                            'order_qty': order_qty,
                                            'total_volume': total_volume,
                                            'to_be_ordered_in_purchase_uom': order_qty_in_purchase_uom}))
        return summary_vals, sum(reorder_total_volume), sum(reorder_total_amount)

    def action_reorder_verified(self):
        summary_vals, reorder_total_volume, reorder_total_amount = self.prepare_reorder_summary_vals()
        reorder_vals = {'is_reorder_line_pending': False, 'state': 'no_data'}
        summary_vals and reorder_vals.update({'summary_ids': summary_vals, 'state': 'verified',
                                              'reorder_total_volume': reorder_total_volume,
                                              'reorder_amount': reorder_total_amount})
        self.write(reorder_vals)
        self.non_forecast_ids and self.non_forecast_ids.unlink()
        return True

    def action_reorder_reset_to_draft(self):
        if self.line_ids:
            self.line_ids.sudo().unlink()
        if self.summary_ids:
            self.summary_ids.sudo().unlink()
        if self.non_forecast_ids:
            self.non_forecast_ids.unlink()
        if self.reorder_classification_ids:
            self.reorder_classification_ids.unlink()
        if self.reorder_stock_movement_ids:
            self.reorder_stock_movement_ids.unlink()
        self.write({'state': 'draft', 'is_reorder_line_pending': False,
                    'reorder_total_volume': 0.0, 'reorder_amount': 0.0})
        return True

    def action_reorder_cancel(self):
        if self.state not in ('done', 'cancel', 'verified'):
            self.write({'state': 'cancel'})
            return True

    def action_purchase_count(self):
        action = self.env["ir.actions.actions"]._for_xml_id("purchase.purchase_form_action")

        purchases = self.mapped('purchase_ids')
        if len(purchases) > 1:
            action['domain'] = [('id', 'in', purchases.ids)]
        elif purchases:
            form_view = [(self.env.ref('purchase.purchase_order_form').id, 'form')]
            if 'views' in action:
                action['views'] = form_view + [(state, view) for state, view in action['views'] if view != 'form']
            else:
                action['views'] = form_view
            action['res_id'] = purchases.id
        return action

    def action_replenishment_count(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "setu_advance_reordering.actions_advance_procurement_process")

        replenishment = self.mapped('replenishment_ids')
        if len(replenishment) > 1:
            action['domain'] = [('id', 'in', replenishment.ids)]
        elif replenishment:
            form_view = [(self.env.ref('setu_advance_reordering.form_advance_procurement_process').id, 'form')]
            if 'views' in action:
                action['views'] = form_view + [(state, view) for state, view in action['views'] if view != 'form']
            else:
                action['views'] = form_view
            action['res_id'] = replenishment.id
        return action

    def _get_date_planned(self, partner_id, product_id, product_qty, start_date):
        days = self.user_id.company_id.po_lead or 0
        days += product_id._select_seller(
            partner_id=partner_id,
            quantity=product_qty,
            date=fields.Date.context_today(self, start_date),
            uom_id=product_id.uom_po_id).delay or 0.0
        date_planned = start_date + relativedelta.relativedelta(days=days)
        return date_planned.strftime(DEFAULT_SERVER_DATETIME_FORMAT)

    def _prepare_purchase_order_line_vals(self, fpos, warehouse_group_id):
        partner = self.vendor_id
        po_line_vals = []

        for summary_line in self.summary_ids:
            product_id = summary_line.product_id
            reorder_line = self.line_ids.filtered(lambda x: x.product_id.id == product_id.id and
                                                            x.warehouse_group_id.id == warehouse_group_id.id and
                                                            x.demand_adjustment_qty > 0.0)
            if reorder_line:
                quantity = 0.0
                if summary_line.demanded_qty <= summary_line.vendor_moq:
                    quantity = (summary_line.vendor_moq * reorder_line.wh_sharing_percentage) / 100
                else:
                    quantity = summary_line.to_be_ordered_in_purchase_uom if summary_line.to_be_ordered_in_purchase_uom > 0 else sum(
                        reorder_line.mapped('demand_adjustment_qty'))

                date_planned = self._get_date_planned(partner, product_id, quantity, datetime.today())
                product_lang = product_id.with_prefetch().with_context(
                    lang=partner.lang,
                    partner_id=partner.id,
                )

                warehouse_id = reorder_line[0].warehouse_group_id and reorder_line[0].warehouse_group_id[
                    0].warehouse_ids
                warehouse_id = warehouse_id and warehouse_id[0] or False

                company_id = warehouse_id and warehouse_id.company_id or False

                if company_id:
                    ps_info = product_id.seller_ids.filtered(lambda
                                                                 x: x.partner_id.id == self.vendor_id.id and x.company_id == company_id and x.currency_id == company_id.currency_id)
                else:
                    ps_info = product_id.seller_ids.filtered(lambda x: x.partner_id.id == self.vendor_id.id)

                ps_info_have_min_qty = ps_info.filtered(lambda x: x.reorder_minimum_quantity > 0)
                if ps_info_have_min_qty:
                    ps_info_have_min_qty = ps_info_have_min_qty.filtered(
                        lambda x: x.reorder_minimum_quantity <= quantity).sorted(
                        key=lambda x: x.reorder_minimum_quantity, reverse=True)
                    if ps_info_have_min_qty:
                        ps_info = ps_info_have_min_qty[0]

                # ps_info = product_id.seller_ids.filtered(lambda x: x.name.id == self.vendor_id.id)
                ps_info = ps_info and len(ps_info) > 1 and ps_info[0] or ps_info

                name = product_lang.display_name
                if product_lang.description_purchase:
                    name += '\n' + product_lang.description_purchase
                taxes = product_id.supplier_taxes_id
                taxes_id = fpos.map_tax(taxes) if fpos else taxes
                if taxes_id:
                    taxes_id = taxes_id.filtered(lambda x: x.company_id.id == self.env.user.company_id.id)

                po_line_vals.append((0, 0, {
                    'name': name,
                    'product_id': product_id.id,
                    'product_qty': round(quantity),
                    'price_unit': ps_info.price,
                    'product_uom': product_id.uom_po_id.id if summary_line.to_be_ordered_in_purchase_uom > 0 else product_id.uom_id.id,
                    'date_planned': date_planned,
                    'taxes_id': [(6, 0, taxes_id.ids)],
                }))
        return po_line_vals

    def create_purchase_order(self, default_warehouse, warehouse_group_id):
        """ Create a purchase order from Advance Reorder
        """
        origins = self.name
        partner = self.vendor_id
        purchase_date = datetime.today()
        company_id = default_warehouse.company_id
        fpos = self.env['account.fiscal.position'].with_company(company_id)._get_fiscal_position(partner)
        fpos = fpos or False
        order_line_vals = self._prepare_purchase_order_line_vals(fpos, warehouse_group_id)
        if not order_line_vals:
            return True
        dates = [fields.Datetime.from_string(value[2]['date_planned']) for value in order_line_vals]
        procurement_date_planned = dates and max(dates) or False
        vals = {
            'partner_id': partner.id,
            'user_id': self.user_id and self.user_id.id or self.env.user.id,
            'picking_type_id': default_warehouse.in_type_id.id,
            'company_id': company_id.id,
            'currency_id': partner.with_company(
                company_id).property_purchase_currency_id.id or company_id.currency_id.id,
            'origin': origins,
            'payment_term_id': partner.with_company(company_id).property_supplier_payment_term_id.id,
            'date_order': purchase_date,
            'fiscal_position_id': fpos.id if fpos else False,
            'order_line': order_line_vals,
            'reorder_process_id': self.id,
            'date_planned': procurement_date_planned,
            'reorder_planner_id': self.reorder_planner_id.id
        }
        return self.env['purchase.order'].with_user(self.user_id).with_company(company_id).create(vals)

    def action_create_reorder_purchase_order(self):
        if not self.summary_ids:
            return True

        if self.vendor_rule in ['both', 'minimum_order_value'] and \
                self.reorder_amount < self.minimum_reorder_amount:
            raise UserError(_("Can not create purchase order because reorder doesn't fulfil "
                              "vendor's minimum order amount's rule."))

        for config_id in self.config_ids:
            self.create_purchase_order(config_id.default_warehouse_id, config_id.warehouse_group_id)
        if self.purchase_ids:
            self.write({'state': 'done'})
        return True

    def create_warehouse_replenishment(self):
        replenishment_obj = self.env['advance.procurement.process']
        for config_id in self.config_ids:
            demand_line_ids = self.line_ids.filtered(lambda x:
                                                     x.warehouse_group_id.id == config_id.warehouse_group_id.id
                                                     and x.demand_adjustment_qty > 0)
            product_ids = demand_line_ids.mapped('product_id').ids
            if not product_ids:
                continue
            vals = {
                'warehouse_id': config_id.default_warehouse_id.id,
                'procurement_date': datetime.today(),
                'user_id': self.user_id.id,
                'buffer_stock_days': self.buffer_security_days,
                'generate_demand_with': self.generate_demand_with,
                'history_sale_start_date': self.sales_start_date,
                'history_sale_end_date': self.sales_end_date,
                'procurement_demand_growth': self.reorder_demand_growth,
                'config_ids': [(0, 0, {'warehouse_id': warehouse.id}) for warehouse in
                               config_id.warehouse_group_id.warehouse_ids],
                'product_ids': [(6, 0, product_ids)],
                'reorder_id': self.id
            }
            replenishment = replenishment_obj.create(vals)
            # replenishment.onchange_procurement_warehouse_id()
            for config in replenishment.config_ids:
                config.onchange_warehouse_id()
                config.onchange_transit_days()
                config.onchange_shipment_arrival_date()
            replenishment.onchange_buffer_security_days()
        return True


class AdvanceReorderNonProductForecast(models.Model):
    _name = 'advance.reorder.non.product.forecast'
    _description = "Advance Reorder for not create Forecast for Product and Warehouse"

    product_id = fields.Many2one('product.product', string="Product")
    warehouse_id = fields.Many2one('stock.warehouse', string="Warehouse")
    period_id = fields.Many2one('reorder.fiscalperiod', "Fiscal Period")
    forecast_qty = fields.Float("Forecast Quantity")
    reorder_process_id = fields.Many2one('advance.reorder.orderprocess', string="Advance Reorder Process")
    procurement_process_id = fields.Many2one('advance.procurement.process', string="Replenishment from Warehouses")
