from datetime import datetime, timedelta
from odoo import fields, models, api, _
from odoo.exceptions import UserError
from statistics import mean
from odoo.exceptions import ValidationError


class AdvanceReorderPlanner(models.Model):
    _name = 'advance.reorder.planner'
    _inherit = ['mail.thread']
    _description = "Advance reorder by demand generation planner"

    def _compute_reorder_count(self):
        for record in self:
            record.reorder_count = len(record.reorder_ids.ids)

    def _compute_purchase_count(self):
        for record in self:
            record.purchase_count = len(record.purchase_ids.ids)

    name = fields.Char("Name", help="Reorder Planner Number")
    vendor_selection_strategy = fields.Selection([('sequence', 'Sequence Of Vendor'),
                                                  ("price", "Cheapest vendor"),
                                                  ("delay", "Quickest vendor"),
                                                  ("specific_vendor", "Specific vendor")],
                                                 string="Vendor selection strategy", default="sequence",
                                                 help="""This field is useful when purchase order is created from order points 
                                                           that time system checks about the vendor which is suitable for placing an order 
                                                           according to need. Whether quickest vendor, cheapest vendor or specific vendor is suitable 
                                                           for the product"""
                                                 )
    state = fields.Selection([('draft', 'Draft'),
                              ('verified', 'Verified')],
                             default="draft", string="Status",
                             help="To identify process status", tracking=True)
    vendor_id = fields.Many2one('res.partner', string="Vendor",
                                help="Set the vendor to whom you want to place an order")
    user_id = fields.Many2one('res.users', string="Responsible", default=lambda self: self.env.user,
                              help="Responsible user")
    buffer_security_days = fields.Integer('Coverage days',
                                          help="Place order for next x days, "
                                               "system will generate demands for next x days after order transit time")
    reorder_demand_growth = fields.Float('Expected growth (%)',
                                         help="Add percentage value if you want to calculate demand with growth")
    generate_demand_with = fields.Selection([('history_sales', 'History Sales'),
                                             ('forecast_sales', 'Forecast Sales')],
                                            string="Demand calculation by",
                                            help="Demand generate based on past sales or forecasted sales",
                                            default='history_sales')
    product_ids = fields.Many2many("product.product", 'reorder_planner_product_rel', 'planner_id', 'product_id',
                                   string="Products")
    products_ids = fields.Many2many("product.product", 'reorder_planner_products_rel', 'planner_id', 'products_id',
                                    string="Products",
                                    compute="_compute_products_ids")
    config_ids = fields.One2many('advance.reorder.orderprocess.config', 'reorder_process_template_id',
                                 string='Reorder configuration', help="Reorder configuration")
    auto_workflow_id = fields.Many2one("advance.reorder.process.auto.workflow", string='Auto Workflow')
    past_days = fields.Integer(string="Past Days", default=365)

    planing_frequency = fields.Integer("Planing Frequency Day")
    next_execution_date = fields.Date("Next Execution Date", default=fields.Date.today)
    previous_execution_date = fields.Date("Previous Execution Date", default=fields.Date.today)
    reorder_count = fields.Integer("Reorder Count", compute="_compute_reorder_count")
    reorder_ids = fields.One2many("advance.reorder.orderprocess", "reorder_planner_id", string="Reorder")
    purchase_ids = fields.One2many('purchase.order', 'reorder_planner_id', string='Purchase orders')
    purchase_count = fields.Integer("purchase Count", compute="_compute_purchase_count")
    active = fields.Boolean(default=True)
    only_out_of_stock_product = fields.Boolean("Only Execute for Out of Stock Product")

    @api.onchange('vendor_selection_strategy')
    def onchange_vendor_selection_strategy(self):
        if self.vendor_selection_strategy != 'specific_vendor':
            value = {'value': {'vendor_id': False}}
        else:
            value = {}
        return value

    # @api.onchange('vendor_id')
    # def onchange_vendor_id(self):
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
    def _compute_products_ids(self):
        for record in self:
            if record.vendor_id:
                products = self.env['product.supplierinfo'].sudo().search(
                    [('partner_id', '=', record.vendor_id.id)]).mapped('product_tmpl_id').mapped(
                    'product_variant_ids').filtered(lambda x: x.active != False and x.purchase_ok != False)
                record.products_ids = products if products else False
            else:
                products = self.env['product.product'].sudo().search([('active', '!=', False),
                                                                      ('purchase_ok', '!=', False)])
                record.products_ids = products if products else False

    def verify_reorder_planing(self):
        if not self.product_ids or not self.config_ids:
            raise UserError('Please add warehouse group in configuration tab or select product')
        self.write({'state': 'verified'})
        return True

    def reset_to_draft(self):
        self.write({'state': 'draft'})
        return True

    def get_vendor_product_mapping_dict(self):
        if self.only_out_of_stock_product:
            warehouse_ids = self.config_ids.mapped('warehouse_group_id').mapped('warehouse_ids')
            query = """
                       Select product_id from get_products_outofstock_data('{}','%s','{}','%s','%s','%s', '%s') 
                       where out_of_stock_qty > 0 
                   """ % (set(self.product_ids.ids), set(warehouse_ids.ids),
                          datetime.today().date() - timedelta(days=self.past_days),
                          datetime.today().date(), self.buffer_security_days)

            self._cr.execute(query)
            product_ids = set([row[0] for row in self._cr.fetchall()])
            product_ids = self.env['product.product'].browse(product_ids)
        else:
            product_ids = self.product_ids
        vendor_product_dict = {}
        if self.vendor_selection_strategy == 'specific_vendor':
            vendor_product_dict.update({self.vendor_id.id: self.product_ids.ids})
        else:
            for product_id in product_ids:
                vendor_id = product_id.with_context({'sory_by': self.vendor_selection_strategy,
                                                     'op_company': self.user_id.company_id})._select_seller(
                    quantity=None)

                if vendor_id.partner_id.id in vendor_product_dict.keys():
                    vendor_product_dict.get(vendor_id.partner_id.id).append(product_id.id)
                    # vendor_product_dict.update({vendor_id.name.id: product_list})
                else:
                    vendor_product_dict.update({vendor_id.partner_id.id: product_id.ids})
        return vendor_product_dict

    def prepare_vales_for_reorder(self, vendor, product_list):
        vendor_id = self.env['res.partner'].browse(vendor)
        product_ids = self.env['product.product'].browse(product_list)
        config_vals = []
        vendor_lead = vendor_id.vendor_pricelist_ids.filtered(
            lambda x: x.product_id.id in product_list or x.product_tmpl_id in product_ids.mapped('product_tmpl_id'))
        calc_base_on = self.env['advance.reordering.settings'].search([]).vendor_lead_days_method
        lead_days = 0
        if calc_base_on == 'static':
            lead_days = self.env['advance.reordering.settings'].search([]).vendor_static_lead_days
        elif calc_base_on == 'max':
            if not vendor_lead:
                raise ValidationError(
                    _("Please ensure that the Vendor is specified in the 'Purchase' tab of all the products that are selected when creating a Reorder with Real Demand Planner."))
            lead_days = max(vendor_lead.mapped('delay'))
        elif calc_base_on == 'minimum':
            if not vendor_lead:
                raise ValidationError(
                    _("Please ensure that the Vendor is specified in the 'Purchase' tab of all the products that are selected when creating a Reorder with Real Demand Planner."))
            lead_days = min(vendor_lead.mapped('delay'))
        elif calc_base_on == 'avg':
            if not vendor_lead:
                raise ValidationError(
                    _("Please ensure that the Vendor is specified in the 'Purchase' tab of all the products that are selected when creating a Reorder with Real Demand Planner."))
            lead_days = mean(vendor_lead.mapped('delay'))
        for config_id in self.config_ids:
            config_vals.append((0, 0, {'warehouse_group_id': config_id.warehouse_group_id.id,
                                       'default_warehouse_id': config_id.default_warehouse_id.id,
                                       'vendor_lead_days': lead_days or 1}))
        vals = {'vendor_id': vendor_id.id,
                'user_id': self.user_id.id,
                'reorder_date': datetime.now(),
                'buffer_security_days': self.buffer_security_days,
                'generate_demand_with': self.generate_demand_with,
                'sales_start_date': datetime.today().date() - timedelta(days=self.past_days),
                'sales_end_date': datetime.today().date(),
                'reorder_demand_growth': self.reorder_demand_growth,
                'volume_uom_name': self.env['advance.reorder.orderprocess']._default_volume_uom_name(),
                'reorder_planner_id': self.id,
                'product_ids': [(6, 0, product_ids.ids)],
                'config_ids': config_vals
                }
        return vals

    def create_real_demand_record(self):
        real_demand_obj = self.env['advance.reorder.orderprocess']
        vendor_product_dict = self.get_vendor_product_mapping_dict()
        for vendor_id, product_ids in vendor_product_dict.items():
            vals = self.prepare_vales_for_reorder(vendor_id, product_ids)
            rec = real_demand_obj.search(
                [('reorder_planner_id', '=', self.id), ('vendor_id', '=', vendor_id), ('state', '=', 'draft')])
            if rec:
                rec.config_ids and rec.config_ids.unlink()
                rec.write(vals)
            else:
                rec = real_demand_obj.create(vals)
            for x in rec.config_ids:
                x.onchange_vendor_lead_days()
                x.onchange_order_arrival_date()

            if self.auto_workflow_id.validate:
                rec.action_reorder_confirm()
            if self.auto_workflow_id.verify:
                rec.action_reorder_verified()
            if self.state == 'verified':
                if self.auto_workflow_id.create_po:
                    rec.action_create_reorder_purchase_order()
                if self.auto_workflow_id.create_replenishment:
                    rec.create_warehouse_replenishment()
                if self.auto_workflow_id.validate_replenishment:
                    for replenishment in rec.replenishment_ids:
                        replenishment.action_procurement_confirm()

            self.write({'previous_execution_date': datetime.today().date(),
                        'next_execution_date': datetime.today().date() + timedelta(days=self.planing_frequency)
                        })

        return True

    def auto_create_real_demand_record(self):
        records = self.search([('next_execution_date', '<=', datetime.today().date()), ('state', '=', 'verified')])
        for record in records:
            record.create_real_demand_record()
        return True

    def action_reorder_count(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "setu_advance_reordering.actions_advance_reorder_orderprocess")
        reorder = self.mapped('reorder_ids')
        if len(reorder) > 1:
            action['domain'] = [('id', 'in', reorder.ids)]
        elif reorder:
            form_view = [(self.env.ref('setu_advance_reordering.form_advance_reorder_orderprocess').id, 'form')]
            if 'views' in action:
                action['views'] = form_view + [(state, view) for state, view in action['views'] if view != 'form']
            else:
                action['views'] = form_view
            action['res_id'] = reorder.id
        return action

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
