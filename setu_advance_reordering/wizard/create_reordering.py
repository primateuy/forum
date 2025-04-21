from odoo import fields, models, api
from odoo.exceptions import UserError


class CreateReordering(models.TransientModel):
    _name = 'create.reordering'

    def _get_purchase_lead_calc_base_on(self):
        return self.env['advance.reordering.settings'].search([]).purchase_lead_calc_base_on

    company_ids = fields.Many2many("res.company", string="Company")
    product_category_ids = fields.Many2many("product.category", string="Product Categories")
    product_ids = fields.Many2many("product.product", string="Products")
    warehouse_ids = fields.Many2many("stock.warehouse", string="Warehouses")
    period_ids = fields.Many2many("reorder.fiscalperiod", string="Periods")
    operation = fields.Selection([('orderpoint', 'Reordering Rule'),
                                  ('sales_history', 'Sales History'),
                                  ('purchase_history', 'Purchase History'),
                                  ('iwt_history', 'IWT History')],
                                 default="orderpoint", string="Operations")

    average_sale_calculation_base = fields.Selection([
        ("monthly_average", "Past 1 Month"),
        ("bi_monthly_average", "Past 2 Month"),
        ("quarterly_average", "Past 3 Month"),
        ("onetwenty_days_average", "Past 4 Month"),
        ("six_month_averagy", "Past 6 Month"),
        ("annual_average", "Past 12 Month")],
        default='quarterly_average',
        string="Safety Stock calculation based on",
        help='It is used in average sales calculation '
             'for Safety Stock calculation, so if it is '
             'set then it will set its value to all the '
             'reordering rules which will be created or '
             'updated from here and calculates the '
             'Safety Stock as per that.')

    consider_current_period_sales = fields.Boolean('Consider Current Period Sales', help='consider current period '
                                                                                         'sales in the sales history'
                                                                                         ' calculation', default=True)

    document_creation_option = fields.Selection([('ict', 'Inter Company Transfer'),
                                                 ('iwt', 'Inter Warehouse Transfer'),
                                                 ('po', 'Purchase Order'),
                                                 ('od_default', 'Odoo Default'), ],
                                                string="Reorder Fullfilment Strategy",
                                                default='od_default',
                                                help="Inter Company Transfer(ICT) - System will create an Inter "
                                                     "Company Transfer.\nInter Warehouse Transfer(IWT) - System will "
                                                     "create an Inter Warehouse Transfer.\nPurchase Order - System "
                                                     "will create a Purchase Order.\n\nNote - ICT and IWT will be "
                                                     "worked as per the configuration of Inter Company Channel.")
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

    orderpoint_operation = fields.Selection([('create_order_point', 'Create Reordering Rule'),
                                             ('update_order_point', 'Update Reordering Rule'),
                                             ],
                                            default="create_order_point", string="Select operation")
    location_selection_strategy = fields.Selection([('lot_stock', 'Warehouse Main Location'),
                                                    ('input', 'Warehouse Input Location'),
                                                    ('specific', 'Specific Location')], default='lot_stock',
                                                   string="Location Selection Strategy")
    specific_location_mapping_ids = fields.One2many('specific.location.mapping', 'wizard_id',
                                                    string="Warehouse - Location Mapping")

    add_purchase_in_lead_calc = fields.Boolean("Purchase", default=True)
    add_iwt_in_lead_calc = fields.Boolean("IWT", default=False)
    static_average_lead_time = fields.Integer("Static Average Lead Time")
    static_maximum_lead_time = fields.Integer("Static Maximum Lead Time")
    purchase_lead_calc_base_on = fields.Selection([('vendor_lead_time', 'Vendor Lead Time'),
                                                   ('real_time', 'Real Time'),
                                                   ('static_lead_time', 'Static Lead Time')
                                                   ], string="Purchase lead calculation base on",
                                                  default=_get_purchase_lead_calc_base_on)
    buffer_days = fields.Integer("Buffer Days")

    @api.onchange('location_selection_strategy')
    def onchange_location_selection_strategy(self):
        if self.location_selection_strategy == 'specific':
            self.warehouse_ids = False

    # @api.onchange('product_category_ids')
    # def onchange_product_category_id(self):
    #     if self.product_category_ids:
    #         return {'domain': {'product_ids': [('categ_id', 'child_of', self.product_category_ids.ids)]}}

    def prepare_orderpoint_domain(self):
        category_ids = company_ids = {}
        # products = []
        # warehouses = []
        # if self.product_category_ids:
        #     products += self.env['product.product'].search([('categ_id','child_of',self.product_category_ids.ids)]).ids
        # elif self.product_ids:
        products = self.product_ids and self.product_ids.ids

        # if self.company_ids:
        #     companies = self.env['res.company'].search([('id', 'child_of', self.company_ids.ids)])
        #     company_ids = set(companies.ids) or {}
        # else:
        #     company_ids = set(self.env.context.get('allowed_company_ids', False) or self.env.user.company_ids.ids) or {}

        warehouses = self.warehouse_ids and self.warehouse_ids.ids or []
        domain = []
        if products:
            domain.append(('product_id', 'in', products))
        if warehouses:
            domain.append(('warehouse_id', 'in', warehouses))

        return domain

    def perform_operation(self):
        operation = self.orderpoint_operation
        if operation == "create_order_point":
            return self.create_reorder_rule()

        elif operation == "update_order_point":
            return self.update_reorder_rule()

        elif operation == "update_order_point_from_suggestion":
            self.update_orderpoint_from_suggestions()

        # elif operation == "export_order_point":
        #     self.export_reorder_rule()
        #
        # elif operation == "import_order_point":
        #     self.import_reorder_rule()

        return True

    def update_orderpoint_from_suggestions(self):
        domain = self.prepare_orderpoint_domain()
        orderpoints = self.env['stock.warehouse.orderpoint'].search(domain)
        if orderpoints:
            orderpoints.update_order_point_data()
        return True

    def update_reorder_rule(self):
        products = self.product_ids and set(self.product_ids.ids) or {}
        warehouses = self.warehouse_ids and set(self.warehouse_ids.ids) or {}
        for period in self.period_ids:
            query = """
                    Select * from update_product_purchase_history('%s','%s','%s','%s','%s')
                """ % (
                products, warehouses, period.fpstartdate.strftime("%Y-%m-%d"),
                period.fpenddate.strftime("%Y-%m-%d"), self.env.user.id)
            self._cr.execute(query)

            query = """
                Select * from update_product_sales_history('{}','%s','{}','%s','%s','%s', '%s')
            """ % (
                products, warehouses, period.fpstartdate.strftime("%Y-%m-%d"),
                period.fpenddate.strftime("%Y-%m-%d"), self.env.user.id)
            self._cr.execute(query)

            query = """
                    Select * from update_product_iwt_history('%s','%s','%s','%s','%s')
                """ % (
                products, warehouses, period.fpstartdate.strftime("%Y-%m-%d"),
                period.fpenddate.strftime("%Y-%m-%d"), self.env.user.id)
            self._cr.execute(query)

        domain = self.prepare_orderpoint_domain()
        orderpoints = self.env['stock.warehouse.orderpoint'].search(domain)

        vals = {'consider_current_period_sales': self.consider_current_period_sales,
                'add_purchase_in_lead_calc': self.add_purchase_in_lead_calc,
                'add_iwt_in_lead_calc': self.add_iwt_in_lead_calc,
                'buffer_days': self.buffer_days}

        if self.average_sale_calculation_base:
            vals.update({'average_sale_calculation_base': self.average_sale_calculation_base})
        if self.document_creation_option:
            vals.update({'document_creation_option': self.document_creation_option})
        if self.vendor_selection_strategy:
            vals.update({'vendor_selection_strategy': self.vendor_selection_strategy})
        if self.vendor_selection_strategy == 'specific_vendor' and self.partner_id:
            vals.update({'partner_id': self.partner_id})
        if self.purchase_lead_calc_base_on == 'static_lead_time':
            vals.update({'max_lead_time': self.static_maximum_lead_time,
                         'avg_lead_time': self.static_average_lead_time})

        orderpoints.write(vals)

        if orderpoints and not self.period_ids:
            orderpoints.update_product_purchase_history()
            orderpoints.update_product_sales_history()
            orderpoints.update_product_iwt_history()
            self._cr.commit()

        for orderpoint_id in orderpoints.ids:
            orderpoint = self.env['stock.warehouse.orderpoint'].browse(orderpoint_id)
            orderpoint._calculate_lead_time()
            orderpoint.calculate_sales_average_max()
            orderpoint.onchange_average_sale_calculation_base()
            orderpoint.onchange_safety_stock()
            orderpoint.onchange_avg_sale_lead_time()
            orderpoint.onchange_safety_stock()

        if orderpoints:
            self._cr.commit()
            orderpoints.update_order_point_data()
        return self.action_orderpoint(orderpoints.ids)

    def reordering_rule_exec(self, products, warehouses, location_type, specific_location=0):
        query = """
                    Select * from create_reordering_rule('{}','%s','{}','%s','%s','%s','%s')
                    """ % (products, warehouses, self.env.user.id, location_type, specific_location)
        self._cr.execute(query)
        inserted_orderpoints_ids = [i[0] for i in self._cr.fetchall()]
        return inserted_orderpoints_ids

    def create_reorder_rule(self):
        location_type = self.location_selection_strategy
        products = self.product_ids and set(self.product_ids.ids) or {}
        inserted_orderpoints_ids = []
        if location_type == 'specific':
            specific_location_mapping_ids = self.specific_location_mapping_ids
            if not specific_location_mapping_ids:
                raise UserError("Please configure warehouses and its specific locations.")
            for mapping in specific_location_mapping_ids:
                op_ids = self.reordering_rule_exec(products, set([mapping.warehouse_id.id]), location_type,
                                                   specific_location=mapping.specific_location_id.id)
                if op_ids:
                    inserted_orderpoints_ids.extend(op_ids)
        else:
            warehouses = self.warehouse_ids
            if not warehouses:
                allowed_company_ids = self.env.context.get('allowed_company_ids', [])
                if allowed_company_ids:
                    warehouses = self.env['stock.warehouse'].sudo().search([]).filtered(
                        lambda x: x.company_id.id in allowed_company_ids)
                    warehouses = warehouses
            for warehouse in warehouses:
                if location_type == 'lot_stock':
                    specific_location = warehouse.lot_stock_id.id
                else:
                    specific_location = warehouse.wh_input_stock_loc_id.id
                op_ids = self.reordering_rule_exec(products, set([warehouse.id]), location_type,
                                                   specific_location=specific_location)
                if op_ids:
                    inserted_orderpoints_ids.extend(op_ids)

        if inserted_orderpoints_ids:
            # orderpoints = self.env['stock.warehouse.orderpoint']
            orderpoints = self.env['stock.warehouse.orderpoint'].browse(inserted_orderpoints_ids)
            if orderpoints and not self.period_ids:
                orderpoints.update_product_purchase_history()
                orderpoints.update_product_sales_history()
                orderpoints.update_product_iwt_history()
                self._cr.commit()

            for record in orderpoints:
                # orderpoint = record#self.env['stock.warehouse.orderpoint'].browse(record)
                vals = {'consider_current_period_sales': self.consider_current_period_sales,
                        'add_purchase_in_lead_calc': self.add_purchase_in_lead_calc,
                        'add_iwt_in_lead_calc': self.add_iwt_in_lead_calc,
                        'buffer_days': self.buffer_days}

                if self.average_sale_calculation_base:
                    vals.update({'average_sale_calculation_base': self.average_sale_calculation_base})
                if self.document_creation_option:
                    vals.update({'document_creation_option': self.document_creation_option})
                if self.vendor_selection_strategy:
                    vals.update({'vendor_selection_strategy': self.vendor_selection_strategy})
                if self.vendor_selection_strategy == 'specific_vendor' and self.partner_id:
                    vals.update({'partner_id': self.partner_id})
                if self.purchase_lead_calc_base_on == 'static_lead_time':
                    vals.update({'max_lead_time': self.static_maximum_lead_time,
                                 'avg_lead_time': self.static_average_lead_time})
                record.with_context(do_not_checked_rule=True).write(vals)

                record.with_context(already_calculated_history=True, do_not_checked_rule=True).recalculate_data()
                # orderpoints += orderpoint
            if orderpoints:
                self._cr.commit()
                orderpoints.update_order_point_data()
            return self.action_orderpoint(orderpoints.ids)
        return True

    def action_orderpoint(self, orderpoints):
        """
        This method will prepare action return.
        :param orderpoints: list of order point ids.
        :return: It will return dictionary of action.
        """
        action = self.env.ref('stock.action_orderpoint').sudo().read()[0]
        action['domain'] = [('id', 'in', orderpoints)]
        return action

    def update_purchase_history(self):
        # category_ids = company_ids = {}
        # if self.product_category_ids:
        #     categories = self.env['product.category'].search([('id', 'child_of', self.product_category_ids.ids)])
        #     category_ids = set(categories.ids) or {}
        products = self.product_ids and set(self.product_ids.ids) or {}

        # if self.company_ids:
        #     companies = self.env['res.company'].search([('id', 'child_of', self.company_ids.ids)])
        #     company_ids = set(companies.ids) or {}
        # else:
        #     company_ids = set(self.env.context.get('allowed_company_ids', False) or self.env.user.company_ids.ids) or {}

        warehouses = self.warehouse_ids and set(self.warehouse_ids.ids) or {}

        for period in self.period_ids:
            query = """
                        Select * from update_product_purchase_history('%s','%s','%s','%s','%s')
                    """ % (
                products, warehouses, period.fpstartdate.strftime("%Y-%m-%d"),
                period.fpenddate.strftime("%Y-%m-%d"), self.env.user.id)
            # print(query)
            self._cr.execute(query)
        action = self.env.ref('setu_advance_reordering.product_purchase_history_action').sudo().read()[0]
        return action

    def update_sales_history(self):
        category_ids = company_ids = {}
        if self.product_category_ids:
            categories = self.env['product.category'].search([('id', 'child_of', self.product_category_ids.ids)])
            category_ids = set(categories.ids) or {}
        products = self.product_ids and set(self.product_ids.ids) or {}

        if self.company_ids:
            companies = self.env['res.company'].search([('id', 'child_of', self.company_ids.ids)])
            company_ids = set(companies.ids) or {}
        else:
            company_ids = set(self.env.context.get('allowed_company_ids', False) or self.env.user.company_ids.ids) or {}

        warehouses = self.warehouse_ids and set(self.warehouse_ids.ids) or {}

        for period in self.period_ids:
            query = """
                Select * from update_product_sales_history('%s','%s','%s','%s','%s','%s', '%s')
            """ % (
                company_ids, products, category_ids, warehouses, period.fpstartdate.strftime("%Y-%m-%d"),
                period.fpenddate.strftime("%Y-%m-%d"), self.env.user.id)
            # print(query)
            self._cr.execute(query)
        action = self.env.ref('setu_advance_reordering.product_sales_history_action').sudo().read()[0]
        return action

    def update_iwt_history(self):
        products = self.product_ids and set(self.product_ids.ids) or {}
        warehouses = self.warehouse_ids and set(self.warehouse_ids.ids) or {}

        for period in self.period_ids:
            query = """
                        Select * from update_product_iwt_history('%s','%s','%s','%s','%s')
                    """ % (
                products, warehouses, period.fpstartdate.strftime("%Y-%m-%d"),
                period.fpenddate.strftime("%Y-%m-%d"), self.env.user.id)
            # print(query)
            self._cr.execute(query)
        action = self.env.ref('setu_advance_reordering.product_iwt_history_action').sudo().read()[0]
        return action


class SpecificLocationMapping(models.TransientModel):
    _name = 'specific.location.mapping'

    orderpoint_id = fields.Many2one('stock.warehouse.orderpoint', string="Orderpoint")
    warehouse_id = fields.Many2one('stock.warehouse', string="Warehouse")
    specific_location_id = fields.Many2one('stock.location', string="Location")
    specific_location_ids = fields.Many2many('stock.location', 'create_reordering_wizard_location_rel',
                                            'reorder_wizard_id', 'products_id', string="Location",
                                            compute="_compute_specific_location_ids")
    wizard_id = fields.Many2one('create.reordering', string='create rule wizard')

    # @api.onchange('warehouse_id')
    # def onchange_warehouse_id(self):
    #     warehouse = self.warehouse_id
    #     if warehouse:
    #         locations = self.env['stock.location'].sudo().search(
    #             [('location_id', 'child_of', warehouse.view_location_id.id),
    #              ('usage', '=', 'internal')])
    #         return {'domain': {'specific_location_id': [('id', 'in', locations.ids)]}}
    #     self.specific_location_id = False
    #     return {'domain': {'specific_location_id': []}}

    @api.depends('warehouse_id')
    def _compute_specific_location_ids(self):
        for record in self:
            if record.warehouse_id:
                locations = self.env['stock.location'].sudo().search(
                [('location_id', 'child_of', record.warehouse_id.view_location_id.id),
                 ('usage', '=', 'internal')])
                record.specific_location_ids = locations if locations else False
            else:
                # locations = self.env['stock.location'].sudo().search([('usage', '=', 'internal')])
                record.specific_location_ids = False
