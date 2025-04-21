from lxml import etree
from datetime import datetime
from dateutil import relativedelta
from odoo import fields, models, api, _
from odoo.exceptions import UserError,ValidationError


class AdvanceProcurementProcess(models.Model):
    _name = 'advance.procurement.process'
    _inherit = ['mail.thread']
    _description = "Advance Procurement Process"
    _order = 'id desc'

    def _compute_count_inter_transfer(self):
        for record in self:
            record.iwt_count = len(record.inter_warehouse_ids)
            record.ict_count = len(record.inter_company_ids)

    def _default_volume_uom_name(self):
        volume_uom = self.env['product.template']._get_volume_uom_id_from_ir_config_parameter()
        return volume_uom and volume_uom.name or ''

    name = fields.Char("Name")
    inter_warehouse_ids = fields.One2many('setu.intercompany.transfer', 'procurement_warehouse_id',
                                          string='Inter warehouses', help="Set Inter Warehouses")
    inter_company_ids = fields.One2many('setu.intercompany.transfer', 'procurement_company_id',
                                        string='Inter companies', help="Set Inter Companies")
    state = fields.Selection([('draft', 'Draft'),
                              ('inprogress', 'In-Progress'),
                              ('verified', 'verified'),
                              ('waiting_for_approval', 'Waiting for Approval'),
                              ('approved', 'Approved'),
                              ('reject', 'Rejected'),
                              ('done', 'Done'),
                              ('unable_to_replenish', 'Unable to Replenish'),
                              ('cancel', 'Cancel')],
                             default="draft", string="Status",
                             help="To identify process status", tracking=True)
    procurement_date = fields.Datetime('Procurement date', default=datetime.now(),
                                       help="Set date and time advance reorder process occur")
    approve_id = fields.Many2one('res.users', string="Approver",
                                 help="Set name of approve user",
                                 domain=lambda self: [('groups_id', 'in',
                                                       self.env.ref(
                                                           'setu_advance_reordering.group_advance_reordering_approved').ids)])
    user_id = fields.Many2one('res.users', string="Responsible",
                              help="Set user who manage reorder process", default=lambda self: self.env.user)
    warehouse_id = fields.Many2one('stock.warehouse', string="Warehouse",
                                   help="Set warehouse for procurement process")
    buffer_stock_days = fields.Integer('Coverage days',
                                       help="Set days to maintain advance stock for products for next days")
    generate_demand_with = fields.Selection([('history_sales', 'History Sales'),
                                             ('forecast_sales', 'Forecast Sales')],
                                            string="Generate demand with",
                                            help="Demand generate based on past sales or future sales")
    config_ids = fields.One2many('advance.procurement.process.config', 'procurement_process_id',
                                 string='Replenishment Configuration',
                                 help="Help for configure replenishment configuration")
    line_ids = fields.One2many('advance.procurement.process.line', 'procurement_process_id',
                               string='Replenishment Lines', help="Set replenishment Line")
    summary_ids = fields.One2many('advance.procurement.process.summary', 'procurement_process_id',
                                  string='Replenishment summary',
                                  help="Replenishment summary which will be carry forwarded in inter warehouse "
                                       "transfer or inter company transfer")
    product_ids = fields.Many2many("product.product", string="Products")
    history_sale_start_date = fields.Date("From date")
    history_sale_end_date = fields.Date("End date")
    procurement_demand_growth = fields.Float('Expected growth (%)',
                                             help="Add percentage value if you want to calculate demand with growth")
    non_forecast_ids = fields.One2many('advance.reorder.non.product.forecast', 'procurement_process_id',
                                       string='Missing forecast records',
                                       help="Products has no forecast records for that particular period and "
                                            "warehouse, add them instantly and recalculate again")
    is_procurement_line_pending = fields.Boolean("Is procurement line pending")
    procurement_total_volume = fields.Float("Total volume", copy=False)
    volume_uom_name = fields.Char('Volume UOM', default=_default_volume_uom_name)
    iwt_count = fields.Integer('IWT count', compute="_compute_count_inter_transfer")
    ict_count = fields.Integer('ICT count', compute="_compute_count_inter_transfer")
    procurement_classification_ids = fields.One2many('reorder.summary.classification',
                                                     'procurement_process_id',
                                                     string='Reorder Classification')
    procurement_stock_movement_ids = fields.One2many('reorder.stock.movement.report',
                                                     'procurement_process_id',
                                                     string='Reorder Stock Movement')
    reorder_id = fields.Many2one('advance.reorder.orderprocess', string='Reorder Id')

    @api.constrains('config_ids')
    def _check_exist_warehouse_in_line(self):
        for replenish in self:
            warehouse_in_lines = replenish.mapped('config_ids.warehouse_id')
            for warehouse in warehouse_in_lines:
                lines_count = len(replenish.config_ids.filtered(lambda line: line.warehouse_id == warehouse))
                if lines_count > 1:
                    raise ValidationError(_('Warehouse already added in configuration.Please select another one'))
        return True
    # def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
    #     res = super(AdvanceProcurementProcess, self).fields_view_get(view_id=view_id, view_type=view_type,
    #                                                                  toolbar=toolbar, submenu=submenu)
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

    @api.onchange('warehouse_id')
    def onchange_procurement_warehouse_id(self):
        if self.warehouse_id:
            self.config_ids = False
            procurement_date = self.procurement_date.date()
            advance_stock_date = (procurement_date +
                                  relativedelta.relativedelta(days=1)).strftime("%Y-%m-%d")
            self.config_ids = [(0, 0, {'warehouse_id': self.warehouse_id.id,
                                       'shipment_date': procurement_date,
                                       'shipment_arrival_date': procurement_date,
                                       'advance_stock_start_date': advance_stock_date,
                                       'advance_stock_end_date': advance_stock_date})]

    @api.onchange('buffer_stock_days')
    def onchange_buffer_security_days(self):
        days = self.buffer_stock_days - 1 if self.buffer_stock_days > 0.0 \
            else self.buffer_stock_days
        for config in self.config_ids:
            config.advance_stock_start_date = (
                    config.shipment_arrival_date + relativedelta.relativedelta(days=1)).strftime("%Y-%m-%d")
            config.advance_stock_end_date = (
                    config.advance_stock_start_date + relativedelta.relativedelta(days=days)).strftime("%Y-%m-%d")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            name = self.env['ir.sequence'].next_by_code('advance.procurement.process')
            vals.update({'name': name})
        res = super(AdvanceProcurementProcess, self).create(vals_list)
        return res

    def check_configuration_product(self):
        if not self.product_ids or not self.config_ids:
            raise UserError('Before validate should add products in Product tab and add warehouse.')
        config_ids = self.config_ids.filtered(lambda x: x.warehouse_id.id != self.warehouse_id.id)
        if not config_ids:
            raise UserError('Please Configure Other Warehouses For Which Replenishment Can Take Place')

    def get_forecast_sales(self, products, warehouses, config):
        non_forecast_query = """SELECT * FROM get_reorder_non_product_forecast('%s','%s','%s',null,'%s' ,'%s','%s')""" \
                             % (self.env.user.id, str(config.shipment_date), str(config.advance_stock_end_date),
                                self.id, products, warehouses)
        self._cr.execute(non_forecast_query)
        non_forecast_data = self._cr.dictfetchall()
        is_forecast = non_forecast_data[0].get('get_reorder_non_product_forecast')
        is_forecast and self.write({'is_procurement_line_pending': True})

        query = """Select * from get_reorder_forecast_data('%s','%s','%s','%s','%s','%s')""" \
                % (str(config.shipment_date), str(config.shipment_arrival_date),
                   str(config.advance_stock_start_date), str(config.advance_stock_end_date),
                   products, warehouses)
        self._cr.execute(query)
        return self._cr.dictfetchall()

    def get_history_sales(self, products, warehouses, start_date, end_date):
        start_date = start_date.strftime("%Y-%m-%d")
        end_date = end_date and end_date.strftime("%Y-%m-%d")
        query = """Select * from get_products_sales_warehouse_group_wise('%s','%s','%s','%s','%s','%s')
        """ % ('{}', products, '{}', warehouses, start_date, end_date)
        self._cr.execute(query)
        return self._cr.dictfetchall()

    def get_sales_data(self, config):
        products = self.product_ids and set(self.product_ids.ids) or {}
        warehouses = config.warehouse_id and set(config.warehouse_id.ids) or {}
        if self.generate_demand_with == 'history_sales':
            return self.get_history_sales(products, warehouses, self.history_sale_start_date,
                                          self.history_sale_end_date)
        else:
            return self.get_forecast_sales(products, warehouses, config)

    def get_stock_move(self, product, config, incoming_qty):
        stock_location_ids = config.warehouse_id.mapped('lot_stock_id').ids
        stock_move_ids = self.env['stock.move'].search([('product_id', '=', product.id),
                                                        ('state', 'not in', ['draft', 'cancel', 'done']),
                                                        ('location_dest_id', 'in', stock_location_ids)]).ids
        return stock_move_ids

    def prepare_reorder_line_vals(self, config, sales_data, generate_demand_with):
        vals = []
        procurement_demand_growth = self.procurement_demand_growth and self.procurement_demand_growth / 100 or 0.0
        reorder_rounding_method = self.env['advance.reordering.settings'].search([]).reorder_rounding_method
        reorder_round_quantity = int(self.env['advance.reordering.settings'].search([]).reorder_round_quantity)
        for data in sales_data:
            product = self.env['product.product'].sudo().browse(data.get('product_id'))
            # product.invalidate_cache()
            wh_available = product.with_context(
                warehouse=config.warehouse_id.id).virtual_available  # product.with_context({'warehouse': config.warehouse_id.id}).virtual_available
            wh_outgoing = product.with_context(warehouse=config.warehouse_id.id).outgoing_qty
            wh_incoming = product.with_context(warehouse=config.warehouse_id.id).incoming_qty
            net_on_hand = wh_available  # - wh_outgoing
            if net_on_hand < 0:
                net_on_hand = 0
            ads = data.get('ads', 0.0)

            if generate_demand_with == 'history_sales':
                ads = procurement_demand_growth and ads + (ads * procurement_demand_growth) or ads
                lead_days_demand = round(ads * config.transit_days, 2)
                expected_sales = self.buffer_stock_days * ads
            else:
                lead_days_demand = data.get('lead_days_demand_stock', 0.0)
                expected_sales = data.get('expected_sales_stock', 0.0)

            transit_demand = lead_days_demand if net_on_hand > lead_days_demand else net_on_hand
            stock_after_transit = net_on_hand - transit_demand

            demand_qty = round(0 if stock_after_transit > expected_sales else
                               expected_sales - stock_after_transit, 2)

            if not self.warehouse_id.id == config.warehouse_id.id:
                demand_qty = round(0 if wh_incoming > demand_qty else
                                   demand_qty - wh_incoming, 2)

            demand_adjustment_qty = demand_qty

            if reorder_round_quantity and not demand_adjustment_qty % reorder_round_quantity == 0.0:
                if reorder_rounding_method == 'round_up' and not demand_qty == 0.0:
                    # c2 = (a + b) - (a % b);
                    demand_adjustment_qty = round((demand_qty + reorder_round_quantity) - (
                            demand_qty % reorder_round_quantity))
                elif reorder_rounding_method == 'round_down' and not demand_qty == 0.0:
                    # c1 = a - (a % b);
                    demand_adjustment_qty = demand_qty - (demand_qty % reorder_round_quantity)

            stock_move_ids = self.get_stock_move(product, config, wh_incoming)

            procurement_line_vals = {
                'warehouse_id': config.warehouse_id.id,
                'procurement_process_id': self.id,
                'product_id': product.id,
                'available_stock': net_on_hand,
                'average_daily_sale': ads,
                'transit_time_sales': transit_demand,
                'stock_after_transit': stock_after_transit,
                'expected_sales': expected_sales,
                'demanded_qty': demand_qty,
                'incoming_qty': wh_incoming,
                # 'demand_adjustment_qty': round(demand_qty, 0),
                'demand_adjustment_qty': demand_adjustment_qty,
                'stock_move_ids': [(6, 0, stock_move_ids)],
            }

            line_id = self.line_ids.filtered(lambda x: x.product_id == product and
                                                       x.warehouse_id == config.warehouse_id)
            if line_id:
                line_id.write(procurement_line_vals)
                continue
            vals.append((0, 0, procurement_line_vals))
        return vals

    def action_procurement_confirm(self):
        self.check_configuration_product()
        vals = []
        procurement_vals = {}
        reorder_classification_vals = []
        stock_movement_vals = []
        for config in self.config_ids:
            sales_data = self.get_sales_data(config)
            vals.extend(self.prepare_reorder_line_vals(config, sales_data, self.generate_demand_with))

        # if self.generate_demand_with == 'history_sales':
        #     products = self.product_ids and set(self.product_ids.ids) or {}
        #     warehouses = self.config_ids and set(list(set(self.config_ids.mapped('warehouse_id').ids))) or {}
        #
        #     reorder_classification_vals = self.env['reorder.summary.classification']. \
        #         prepare_reorder_classification(products, warehouses, self.history_sale_start_date,
        #                                        self.history_sale_end_date, self.procurement_classification_ids)
        #
        #     stock_movement_vals = self.env['reorder.stock.movement.report']. \
        #         prepare_stock_movement_report(products, warehouses, self.history_sale_start_date,
        #                                       self.history_sale_end_date, self.procurement_stock_movement_ids)
        if not self.state == 'inprogress':
            procurement_vals = {'state': 'unable_to_replenish'}
        vals and procurement_vals.update({'line_ids': vals, 'state': 'inprogress'})
        self.write(procurement_vals)
        # 'procurement_classification_ids': reorder_classification_vals,
        # 'procurement_stock_movement_ids': stock_movement_vals})
        return True

    def action_recalculate_procurement_demand(self):
        self.action_procurement_confirm()
        if not self.non_forecast_ids and self.is_procurement_line_pending:
            self.write({'is_procurement_line_pending': False})
        return True

    def action_procurement_create_forecast_sale(self):
        non_forecast_ids = self.non_forecast_ids.filtered(lambda x: x.forecast_qty)
        self.env['advance.reorder.orderprocess'].action_reorder_create_forecast_sale(non_forecast_ids)
        return True

    def prepare_reorder_summary_vals(self):
        summary_vals = []
        reorder_total_volume = []
        for product in self.product_ids:
            lines = self.line_ids.filtered(lambda x: x.product_id.id == product.id)

            if lines:
                # Find demand of procurement warehouse
                main_wh_procurement_line = lines.filtered(lambda x: x.warehouse_id.id == self.warehouse_id.id)

                # Find the demand of another warehouse
                other_wh_procurement_line = lines.filtered(lambda x: x.warehouse_id.id != self.warehouse_id.id
                                                                     and x.demand_adjustment_qty > 0.0)

                if (not main_wh_procurement_line and not other_wh_procurement_line) or (
                        main_wh_procurement_line and not other_wh_procurement_line):
                    continue

                main_wh_demand = sum(main_wh_procurement_line.mapped('demand_adjustment_qty'))
                other_wh_demand = sum(other_wh_procurement_line.mapped('demand_adjustment_qty'))
                if main_wh_procurement_line:
                    main_wh_available_qty = sum(
                        main_wh_procurement_line.filtered(lambda x: x.available_stock > 0.0).mapped('available_stock'))
                else:
                    wh_available = product.with_context({'warehouse': self.warehouse_id.id}).qty_available
                    wh_outgoing = product.with_context({'warehouse': self.warehouse_id.id}).outgoing_qty
                    main_wh_available_qty = wh_available - wh_outgoing
                # main_wh_available_qty = sum(main_wh_procurement_line.filtered(lambda x: x.available_stock > 0.0).mapped('available_stock'))

                if not other_wh_demand or not main_wh_available_qty:
                    continue

                for line_id in other_wh_procurement_line:
                    line_id.wh_sharing_percentage = round(
                        (line_id.demand_adjustment_qty / other_wh_demand) * 100) or 0.0

                available_qty = main_wh_available_qty - main_wh_demand
                if available_qty <= 0.0:
                    continue

                order_qty = other_wh_demand
                if other_wh_demand > available_qty:
                    order_qty = available_qty

                if order_qty <= 0:
                    continue
                weight = product.weight
                if weight <= 0:
                    weight = 1
                total_volume = order_qty * product.volume * weight
                reorder_total_volume.append(total_volume)
                summary_vals.append((0, 0, {'product_id': product.id,
                                            'warehouse_demand_qty': main_wh_demand,
                                            'demanded_qty': other_wh_demand,
                                            'available_qty': available_qty,
                                            'order_qty': order_qty,
                                            'total_volume': total_volume}))
        return summary_vals, sum(reorder_total_volume)

    def action_procurement_verified(self):
        summary_vals, reorder_total_volume = self.prepare_reorder_summary_vals()
        procurement_vals = {'is_procurement_line_pending': False, 'state': 'unable_to_replenish'}
        summary_vals and procurement_vals.update({'summary_ids': summary_vals, 'state': 'verified',
                                                  'procurement_total_volume': reorder_total_volume})
        self.write(procurement_vals)
        self.non_forecast_ids and self.non_forecast_ids.unlink()
        return True

    def action_procurement_reset_to_draft(self):
        if self.line_ids:
            self.line_ids.sudo().unlink()
        if self.summary_ids:
            self.summary_ids.sudo().unlink()
        if self.non_forecast_ids:
            self.non_forecast_ids.unlink()
        if self.procurement_classification_ids:
            self.procurement_classification_ids.unlink()
        if self.procurement_stock_movement_ids:
            self.procurement_stock_movement_ids.unlink()
        self.write({'state': 'draft', 'is_procurement_line_pending': False, 'procurement_total_volume': 0.0})
        return True

    def action_procurement_cancel(self):
        if self.state not in ('done', 'cancel', 'verified'):
            self.write({'state': 'cancel', 'is_procurement_line_pending': False})
            return True

    def action_inter_warehouse_transfer_view(self):
        if self.inter_warehouse_ids:
            report_display_views = []
            form_view_id = self.env.ref('setu_intercompany_transaction.setu_interwareouse_transfer_form').id
            tree_view_id = self.env.ref('setu_intercompany_transaction.setu_interwarehouse_transfer_tree').id
            report_display_views.append((tree_view_id, 'tree'))
            report_display_views.append((form_view_id, 'form'))

            return {
                'name': _('Inter Warehouse Transactions'),
                'domain': [('id', 'in', self.inter_warehouse_ids.ids)],
                'res_model': 'setu.intercompany.transfer',
                'view_mode': "tree,form",
                'type': 'ir.actions.act_window',
                'views': report_display_views,
            }

    def action_inter_company_transfer_view(self):
        if self.inter_company_ids:
            report_display_views = []
            form_view_id = self.env.ref('setu_intercompany_transaction.setu_intercompany_transfer_form').id
            tree_view_id = self.env.ref('setu_intercompany_transaction.setu_intercompany_transfer_tree').id
            report_display_views.append((tree_view_id, 'tree'))
            report_display_views.append((form_view_id, 'form'))

            return {
                'name': _('Inter Company Transactions'),
                'domain': [('id', 'in', self.inter_company_ids.ids)],
                'res_model': 'setu.intercompany.transfer',
                'view_mode': "tree,form",
                'type': 'ir.actions.act_window',
                'views': report_display_views,
            }

    def create_ict_lines(self, summary_ids, config_id):
        ict_lines = []
        warehouse_id = config_id.warehouse_id.id
        for summary_line in summary_ids:
            product_id = summary_line.product_id
            procurement_line = self.line_ids.filtered(lambda x: x.product_id.id == product_id.id
                                                                and x.demand_adjustment_qty > 0.0
                                                                and x.warehouse_id.id == warehouse_id)
            if procurement_line:
                quantity = 0.0
                if summary_line.demanded_qty <= summary_line.available_qty:
                    quantity = sum(procurement_line.mapped('demand_adjustment_qty'))
                else:
                    quantity = round((summary_line.order_qty * procurement_line.wh_sharing_percentage) / 100)
                ict_lines.append((0, 0, {'product_id': product_id.id,
                                         'quantity': quantity,
                                         'unit_price': product_id.lst_price}))
        return ict_lines

    # Create Inter company Transfer Record (ICT)
    def create_inter_company_transfer(self, config_id):
        inter_company_channel_obj = self.env['setu.intercompany.channel']
        inter_company_transfer_obj = self.env['setu.intercompany.transfer']
        ict_lines = self.create_ict_lines(self.summary_ids, config_id)
        if ict_lines:
            ict_vals = inter_company_channel_obj.prepare_intercompany_vals_from_adv(config_id.warehouse_id,
                                                                                    config_id.inter_company_channel_id)
            ict_vals.update({'procurement_company_id': self.id,
                             'intercompany_transfer_line_ids': ict_lines})
            if not ict_vals.get('fulfiller_warehouse_id'):
                ict_vals.update({'fulfiller_warehouse_id': self.warehouse_id.id})
            ict = inter_company_transfer_obj.create(ict_vals)
            ict.onchange_requestor_warehouse_id()
            ict.onchange_fulfiller_warehouse_id()
            ict.pricelist_id = config_id.inter_company_channel_id.pricelist_id.id
            inter_company_channel_obj.execute_workflow(ict)
            ict.mapped('intercompany_transfer_line_ids').product_id_change()
        return True

    # Create Inter warehouse Transfer Record (IWT)
    def create_inter_warehouse_transfer(self, config_id):
        inter_warehouse_channel_obj = self.env['setu.interwarehouse.channel']
        inter_company_transfer_obj = self.env['setu.intercompany.transfer']
        inter_warehouse_channel_id = config_id.inter_warehouse_channel_id

        iwt_lines = self.create_ict_lines(self.summary_ids, config_id)
        if iwt_lines:
            iwt_vals = inter_warehouse_channel_obj.prepare_interwarehouse_values(config_id.warehouse_id,
                                                                                 inter_warehouse_channel_id)
            iwt_vals.update({'procurement_warehouse_id': self.id,
                             'intercompany_transfer_line_ids': iwt_lines})
            if not iwt_vals.get('fulfiller_warehouse_id'):
                iwt_vals.update({'fulfiller_warehouse_id': self.warehouse_id.id})
            iwt = inter_company_transfer_obj.create(iwt_vals)

            iwt.onchange_requestor_warehouse_id()
            iwt.onchange_fulfiller_warehouse_id()
            location = inter_warehouse_channel_id.location_id
            if location:
                iwt.location_id = location.id
            if iwt.state == 'draft' and inter_warehouse_channel_id.validate_ict:
                iwt.action_validate_internal_transfer()
        return True

    def action_procurement_internal_transfer(self):
        own_company = self.warehouse_id.company_id.id
        for config_id in self.config_ids.filtered(lambda x: x.warehouse_id != self.warehouse_id):
            if not own_company == config_id.warehouse_id.company_id.id:
                self.create_inter_company_transfer(config_id)
            elif own_company == config_id.warehouse_id.company_id.id:
                self.create_inter_warehouse_transfer(config_id)
        self.write({'state': 'done'})
        return True
