from datetime import datetime
from odoo import fields, models, api, _
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from dateutil import relativedelta
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

STATE = [('draft', 'New'),
         ('in_progress','In Progress'),
         ('done', 'Done'),
         ('cancel', 'Cancel')]


class SetuIntercompanyTransfer(models.Model):
    _name = 'setu.intercompany.transfer'
    _order = 'ict_date desc, id desc'
    _description = """
        Intercompany Transfer
        ==========================================================
        This app is used to keep track of all the transactions between two warehouses, source warehouse
        and destination warehouse can be of same company and can be of different company.
        
        This app will perform following operations.
        -> Inter company transaction (transaction between warehouses of two different companies)
        -> Inter warehouse transaction (transaction between warehouses of same company)
        -> Reverse transactions (Inter company or Inter warehouse)
        
        Advance features
        -> Define inter company rules which will create inter comapny transactions record automatically
        -> Manage serial number and lot number in Inter company transfers
    """

    name = fields.Char("Name")
    ict_date = fields.Date("Date", copy=False, default=datetime.today())
    requestor_warehouse_id = fields.Many2one("stock.warehouse", "Requestor Warehouse")
    fulfiller_warehouse_id = fields.Many2one("stock.warehouse", "Fulfiller Warehouse")
    requestor_partner_id = fields.Many2one("res.partner", "Requestor Partner", change_default=True, )
    fulfiller_partner_id = fields.Many2one("res.partner", "Fulfiller Partner", change_default=True, )
    requestor_company_id = fields.Many2one("res.company", "Requestor Company", change_default=True, )
    fulfiller_company_id = fields.Many2one("res.company", "Fulfiller Company", change_default=True, )
    pricelist_id = fields.Many2one('product.pricelist', 'Pricelist')
    sales_team_id = fields.Many2one("crm.team", "Sales Team")
    ict_user_id = fields.Many2one("res.users", "Inter Company User")
    origin_order_id = fields.Many2one("sale.order", "Origin Sale Order", copy=False, index=True)
    origin_ict_id = fields.Many2one("setu.intercompany.transfer", "Origin ICT", copy=False)
    intercompany_channel_id = fields.Many2one("setu.intercompany.channel", "Intercompany Channel", copy=False)
    interwarehouse_channel_id = fields.Many2one("setu.interwarehouse.channel", "Interwarehouse Channel", copy=False)
    auto_workflow_id = fields.Many2one("setu.ict.auto.workflow", "Auto workflow")
    transfer_with_single_picking = fields.Boolean("Direct transfer to destination without transit location?", help="""
        This option is useful to transfer stock between two warehouses directly without moving stock to transit location.
        By default stock will be transferred in two step
            1. Source Location to Transit Location
            2. Transit Location to Destination Location
    """)
    location_id = fields.Many2one("stock.location", string="Destination location",
                                  # domain=_get_location_domain,
                                  help="IWT will be created for this location from the fulfiller warehouse.")
    # location_src_id = fields.Many2one("stock.location", string="Source location",
    #                                   help="IWT will be created from this location to the requestor warehouse.")
    manage_lot_serial = fields.Boolean("Manage serial / lot number in Inter Company Transactions?", help="""
            This option helps to manage lot/serial number automatically in requestor company.
            Lot /Serial number which are set in fulfiller company's delivery will set directly in requestor company's incoming shipmenet
        """)
    # direct_deliver_to_customer = fields.Boolean("Direct deliver to origin sale order's customer?", help="""
    #         If requester company wants to deliver his order directly to it's sale order's customer then
    #         this option must be selected.
    #         If this option is selected fulfiller company will deliver stock to requestor company's order
    #         Note:
    # 		it will close incoming shipment of requestor company when destination company deliver order to customer
    #     """)
    transfer_type = fields.Selection([('inter_company', "Inter Company"),
                                      ('inter_warehouse', 'Inter Warehouse'),
                                      ('reverse_transfer', 'Reverse Transfer')], "Transfer Type")
    intercompany_transfer_line_ids = fields.One2many("setu.intercompany.transfer.line", "intercompany_transfer_id",
                                                     "Intercompany Transfer Lines")
    state = fields.Selection(STATE, string='State', readonly=True,
                             copy=False, index=True, default='draft', compute='_compute_state', store=True)
    picking_ids = fields.One2many('stock.picking', 'ict_internal_transfer_id', string='Pickings')
    delivery_count = fields.Integer(string='Total Pickings', compute='_compute_picking_ids')

    purchase_ids = fields.One2many('purchase.order', 'intercompany_transfer_id', string='Purchases')
    purchase_count = fields.Integer(string='Total Purchase', compute='_compute_purchase_ids')
    sale_ids = fields.One2many('sale.order', 'intercompany_transfer_id', string='Sales')
    sale_count = fields.Integer(string='Total Sale', compute='_compute_sale_ids')
    invoice_ids = fields.One2many('account.move', 'intercompany_transfer_id', string='Invoices')
    invoice_count = fields.Integer(string='Total Invoice', compute='_compute_invoice_ids')
    locations_ids = fields.Many2many('stock.location', string='Locations',compute='_compute_locations_id', store=True)

    @api.depends('picking_ids.state', 'sale_ids.picking_ids.state', 'purchase_ids.picking_ids.state')
    def _compute_state(self):
        for rec in self:
            all_picking_ids = rec.picking_ids | rec.sale_ids.mapped('picking_ids') | rec.purchase_ids.mapped(
                'picking_ids')
            if all_picking_ids:
                all_done = all(picking.state == 'done' for picking in all_picking_ids)
                all_cancelled = all(picking.state == 'cancel' for picking in all_picking_ids)
                if all_done:
                    rec.state = 'done'
                elif all_cancelled:
                    rec.state = 'cancel'
                else:
                    rec.state = 'in_progress'

    @api.depends('picking_ids')
    def _compute_picking_ids(self):
        for internal_transfer in self:
            internal_transfer.delivery_count = len(internal_transfer.picking_ids)

    @api.depends('invoice_ids')
    def _compute_invoice_ids(self):
        for ict in self:
            ict.invoice_count = len(ict.invoice_ids)

    @api.depends('sale_ids')
    def _compute_sale_ids(self):
        for ict in self:
            ict.sale_count = len(ict.sale_ids)

    @api.depends('purchase_ids')
    def _compute_purchase_ids(self):
        for ict in self:
            ict.purchase_count = len(ict.purchase_ids)

    @api.depends('requestor_warehouse_id.view_location_id')
    def _compute_locations_id(self):
        for record in self:
            if record.requestor_warehouse_id:
                # record.location_id = False
                view_location_id = record.requestor_warehouse_id.view_location_id
                if view_location_id:
                    locations = record.env['stock.location'].sudo().search(
                        [('parent_path', 'ilike', '%%/%d/%%' % view_location_id.id),
                         ('usage', '=', 'internal')])
                    if locations:
                        record.locations_ids = locations if locations else False

    @api.onchange('requestor_warehouse_id')
    def onchange_requestor_warehouse_id(self):
        if self.requestor_warehouse_id:
            self.requestor_company_id = self.requestor_warehouse_id.company_id
            self.requestor_partner_id = self.requestor_warehouse_id.company_id.partner_id

            # if self.intercompany_channel_id and self.intercompany_channel_id.pricelist_id:
            #     self.pricelist_id = self.intercompany_channel_id.pricelist_id.id
            # else:
            #     self.pricelist_id = self.requestor_partner_id.property_product_pricelist and self.requestor_partner_id.property_product_pricelist.id or False
        #     self.location_id = False
        #     view_location_id = self.requestor_warehouse_id.view_location_id
        #     if view_location_id:
        #         locations = self.env['stock.location'].sudo().search(
        #             [('parent_path', 'ilike', '%%/%d/%%' % view_location_id.id),
        #              ('usage', '=', 'internal')])
        #         print(locations)
        #         if locations:
        #             return {'domain': {'location_id': [('id', 'in', locations.ids)]}}
        # return {'domain': {'location_id': [('id', 'in', [])]}}

    @api.onchange('fulfiller_warehouse_id')
    def onchange_fulfiller_warehouse_id(self):
        if self.fulfiller_warehouse_id:
            self.fulfiller_company_id = self.fulfiller_warehouse_id.company_id
            self.fulfiller_partner_id = self.fulfiller_warehouse_id.company_id.partner_id
            self.pricelist_id = self.fulfiller_partner_id.sudo().with_company(
                self.fulfiller_company_id).property_product_pricelist or False
        #     view_location_id = self.fulfiller_warehouse_id.view_location_id
        #     if view_location_id:
        #         locations = self.env['stock.location'].sudo().search(
        #             [('parent_path', 'ilike', '%%/%d/%%' % view_location_id.id),
        #              ('usage', '=', 'internal')])
        #         if locations:
        #             return {'domain': {'location_src_id': [('id', 'in', locations.ids)]}}
        # return {'domain': {'location_src_id': [('id', 'in', [])]}}

    @api.onchange('origin_ict_id')
    def onchange_origin_ict_id(self):
        if self.origin_ict_id:
            self.requestor_warehouse_id = self.origin_ict_id.requestor_warehouse_id.id
            self.fulfiller_warehouse_id = self.origin_ict_id.fulfiller_warehouse_id.id
            self.pricelist_id = self.origin_ict_id.pricelist_id.id
            self.transfer_with_single_picking = self.origin_ict_id.transfer_with_single_picking
            self.ict_user_id = self.origin_ict_id.ict_user_id.id
            line_ids = [line.copy(default={'intercompany_transfer_id': self.id}).id for line in
                        self.origin_ict_id.intercompany_transfer_line_ids]
            self.intercompany_transfer_line_ids = [(6, 0, line_ids)]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            transfer_type = vals['transfer_type']
            name = False
            if transfer_type == "inter_company":
                name = self.env['ir.sequence'].next_by_code('setu.intercompany.transfer') or _('New')
            elif transfer_type == "inter_warehouse":
                name = self.env['ir.sequence'].next_by_code('setu.interwarehouse.transfer') or _('New')
            elif transfer_type == "reverse_transfer":
                name = self.env['ir.sequence'].next_by_code('setu.reverse.intercompany.transfer') or _('New')

            vals['name'] = name
            result = super(SetuIntercompanyTransfer, self).create(vals)
        return result

    def unlink(self):
        for record in self:
            document = 'Inter Company Transfer' if record.transfer_type != "inter_warehouse" else "Inter Warehouse " \
                                                                                                  "Transfer"
            if record.state == 'done':
                raise ValidationError("Done %s can not be deleted." % document)
        return super(SetuIntercompanyTransfer, self).unlink()

    def action_validate_internal_transfer(self):
        if self.transfer_with_single_picking:
            self.create_direct_picking()
        else:
            transit_location = self.env['stock.location'].search(
                [('usage', '=', 'transit'), ('company_id', '=', self.requestor_company_id.id)], limit=1)
            if not transit_location:
                raise ValidationError(_("To Create Inter Warehouse Transfer With Transit Location, First Please Create Transit Location."))
            self.create_two_step_pickings()
        self.state = "in_progress"
        return True

    def action_reverse_internal_transfer(self):
        """
            This method will be used to create reverse transfer record.
            When user clicked on return button on INter Warehouse TRansfer or inter company transfer this method will be called
        :return:
        """
        vals = {
            'origin_ict_id': self.id,
            'transfer_type': 'reverse_transfer',
        }
        rict = self.env['setu.intercompany.transfer'].create(vals)
        rict.onchange_origin_ict_id()
        rict.onchange_requestor_warehouse_id()
        rict.onchange_fulfiller_warehouse_id()

        report_display_views = []
        form_view_id = self.env.ref('setu_intercompany_transaction.setu_reverse_transfer_form').id
        tree_view_id = self.env.ref('setu_intercompany_transaction.setu_reverse_transfer_tree').id
        report_display_views.append((tree_view_id, 'tree'))
        report_display_views.append((form_view_id, 'form'))

        return {
            'name': _('Reverse Transactions'),
            'domain': [('id', 'in', [rict.id])],
            'res_model': 'setu.intercompany.transfer',
            'view_mode': "tree,form",
            'type': 'ir.actions.act_window',
            'views': report_display_views,
        }

    def action_validate_reverse_transfer(self):
        if not self.origin_ict_id and self.requestor_warehouse_id.company_id.id == self.fulfiller_warehouse_id.company_id.id:
            if self.transfer_with_single_picking:
                self.create_direct_reverse_picking()
            else:
                self.create_two_step_reverse_pickings()
            self.state = "in_progress"
            return True

        if self.origin_ict_id.transfer_type == "inter_company":
            if self.origin_ict_id.sale_ids.mapped("picking_ids").filtered(lambda x: x.state != "done"):
                raise UserError("You can't create return for undelivered sales")

            if self.origin_ict_id.purchase_ids.mapped("picking_ids").filtered(lambda x: x.state != "done"):
                raise UserError("You can't create return for purchase orders which is not received yet")

            so_context = {'default_company_id': self.fulfiller_company_id.id, }

            warehouse = self.origin_ict_id.fulfiller_warehouse_id
            picking_type_id = self.origin_ict_id.fulfiller_warehouse_id.in_type_id.id
            partner_id = self.origin_ict_id.with_company(self.fulfiller_company_id).requestor_partner_id.id
            src_location_id = self.with_company(self.fulfiller_company_id).get_customer_location()
            dest_location_id = warehouse.with_company(self.fulfiller_company_id).lot_stock_id.id

            self.with_user(self.ict_user_id).with_company(self.fulfiller_company_id).create_direct_reverse_picking(
                src_location_id=src_location_id, dest_location_id=dest_location_id,
                warehouse=warehouse, partner_id=partner_id, picking_type_id=picking_type_id)

            po_context = {'default_company_id': self.requestor_company_id.id, }

            warehouse = self.origin_ict_id.requestor_warehouse_id
            picking_type_id = self.origin_ict_id.requestor_warehouse_id.out_type_id.id
            partner_id = self.origin_ict_id.with_company(self.requestor_company_id).fulfiller_partner_id.id
            src_location_id = warehouse.with_company(self.requestor_company_id).lot_stock_id.id
            dest_location_id = self.with_company(self.requestor_company_id).get_vendor_location()

            self.with_user(self.ict_user_id).with_company(self.requestor_company_id).create_direct_reverse_picking(
                src_location_id=src_location_id, dest_location_id=dest_location_id,
                warehouse=warehouse, partner_id=partner_id, picking_type_id=picking_type_id)

            self.state = "in_progress"
            return True
        elif self.requestor_warehouse_id.company_id.id != self.fulfiller_warehouse_id.company_id.id:
            so_context = {'default_company_id': self.fulfiller_company_id.id, }
            warehouse = self.fulfiller_warehouse_id
            picking_type_id = self.fulfiller_warehouse_id.in_type_id.id
            partner_id = self.with_company(self.fulfiller_company_id).requestor_partner_id.id
            src_location_id = self.with_company(self.fulfiller_company_id).get_customer_location()
            dest_location_id = warehouse.with_company(self.fulfiller_company_id).lot_stock_id.id

            self.with_user(self.ict_user_id).with_company(self.fulfiller_company_id).create_direct_reverse_picking(
                src_location_id=src_location_id, dest_location_id=dest_location_id,
                warehouse=warehouse, partner_id=partner_id, picking_type_id=picking_type_id)

            po_context = {'default_company_id': self.requestor_company_id.id, }
            warehouse = self.requestor_warehouse_id
            picking_type_id = self.requestor_warehouse_id.out_type_id.id
            partner_id = self.with_company(self.requestor_company_id).fulfiller_partner_id.id
            src_location_id = warehouse.with_company(self.requestor_company_id).lot_stock_id.id
            dest_location_id = self.with_company(self.requestor_company_id).get_vendor_location()

            self.with_user(self.ict_user_id).with_company(self.requestor_company_id).create_direct_reverse_picking(
                src_location_id=src_location_id, dest_location_id=dest_location_id,
                warehouse=warehouse, partner_id=partner_id, picking_type_id=picking_type_id)

            self.state = "in_progress"
            return True
        elif self.origin_ict_id.transfer_type == "inter_warehouse":
            if self.origin_ict_id.transfer_with_single_picking:
                self.create_direct_reverse_picking()
            else:
                self.create_two_step_reverse_pickings()
            self.state = "in_progress"
            return True
        return True

    def prepare_picking_vals(self, src_location_id=False, dest_location_id=False, warehouse=False, partner_id=False,picking_type_id=False):
        picking_vals = {
            'ict_internal_transfer_id': self.id,
            'partner_id': partner_id or self.requestor_warehouse_id.partner_id.id,
            'origin': self.name,
            'company_id': warehouse and warehouse.company_id.id or self.requestor_company_id.id,
            'picking_type_id': picking_type_id or (warehouse and warehouse.int_type_id.id or self.requestor_warehouse_id.int_type_id.id),
            'location_id': src_location_id or self.fulfiller_warehouse_id.lot_stock_id.id,
            'location_dest_id': dest_location_id or self.requestor_warehouse_id.lot_stock_id.id,
            'state': 'draft',
            'user_id': self.ict_user_id and self.ict_user_id.id or self.env.user.id,
            'scheduled_date': self.origin_order_id and self.origin_order_id.picking_ids and
                              self.origin_order_id.picking_ids[0].scheduled_date or fields.Datetime.now()
        }
        return picking_vals

    def procurement_group_vals(self, partner_id=False):
        group_vals = {
            'name': self.name,
            'move_type': 'direct',
            'partner_id': partner_id or self.requestor_warehouse_id.partner_id.id,
        }

    def get_trasit_location(self):
        return self.env['stock.location'].search(
            [('usage', '=', 'transit'), ('company_id', '=', self.requestor_company_id.id)], limit=1).id

    def get_customer_location(self):
        return self.env['stock.location'].search([('usage', '=', 'customer')], limit=1).id

    def get_vendor_location(self):
        return self.env['stock.location'].search([('usage', '=', 'supplier')], limit=1).id

    def get_location_route(self):
        if self.transfer_with_single_picking:
            return False
        route = self.env['stock.location.route'].search([('supplied_wh_id', '=', self.requestor_warehouse_id.id),
                                                         ('supplier_wh_id', '=', self.fulfiller_warehouse_id.id)])
        return route

    def get_location_rule(self, src_location_id, dest_location_id):
        if self.transfer_with_single_picking:
            return False
        route = self.get_location_route()
        domain = [('route_id', '=', route.id), ('location_src_id', '=', src_location_id.id),
                  ('location_dest_id', '=', dest_location_id.id)]
        return self.env['stock.rule'].search(domain)

    def prepare_move_vals(self, src_location_id=False, dest_location_id=False, warehouse=False, partner_id=False,picking_type_id=False):
        move_vals = []
        group = self.env['procurement.group'].create(self.procurement_group_vals(partner_id=partner_id))

        for line in self.intercompany_transfer_line_ids:
            if not line.product_id:
                continue
            product_lang = line.product_id.with_prefetch().with_context(
                lang=self.fulfiller_warehouse_id.partner_id.lang,
                partner_id=self.fulfiller_warehouse_id.partner_id.id,
            )
            name = product_lang.display_name or line.product_id.default_code
            move_vals.append((0, 0, {
                'name': name,
                'origin': self.name,
                'company_id': warehouse and warehouse.company_id.id or self.requestor_company_id.id,
                'picking_type_id': picking_type_id or (
                        warehouse and warehouse.int_type_id.id or self.requestor_warehouse_id.int_type_id.id),
                'location_id': src_location_id or self.fulfiller_warehouse_id.lot_stock_id.id,
                'location_dest_id': dest_location_id or self.requestor_warehouse_id.lot_stock_id.id,
                'state': 'draft',
                'product_id': line.product_id.id,
                'product_uom_qty': round(line.product_uom_id._compute_quantity(qty=line.quantity, to_unit=line.product_id.uom_id)),
                'product_uom': line.product_id.uom_id.id,
                'product_packaging_id': line.product_packaging_id.id,
                'group_id': group and group.id or False,
                'date_deadline': self.origin_order_id and self.origin_order_id.picking_ids and
                                 self.origin_order_id.picking_ids[0].scheduled_date or fields.Datetime.now(),

            }))
        return move_vals


    def create_direct_reverse_picking(self, src_location_id=False, dest_location_id=False, warehouse=False,
                                      partner_id=False, picking_type_id=False):
        src_location_id = src_location_id or self.requestor_warehouse_id.lot_stock_id.id
        dest_location_id = dest_location_id or self.fulfiller_warehouse_id.lot_stock_id.id
        warehouse = warehouse or self.requestor_warehouse_id
        partner_id = partner_id or self.fulfiller_warehouse_id.partner_id.id
        picking_vals = self.prepare_picking_vals(src_location_id=src_location_id, dest_location_id=dest_location_id,
                                                 warehouse=warehouse, partner_id=partner_id,
                                                 picking_type_id=picking_type_id)
        picking_vals.update({'move_ids_without_package': self.prepare_move_vals(src_location_id=src_location_id,
                                                                                dest_location_id=dest_location_id,
                                                                                warehouse=warehouse,
                                                                                partner_id=partner_id,
                                                                                picking_type_id=picking_type_id)})

        # picking_context = {'default_company_id': warehouse.company_id.id,}
        picking = self.env['stock.picking'].with_company(warehouse.company_id).create(picking_vals)
        picking.with_company(warehouse.company_id).action_confirm()
        picking.with_company(warehouse.company_id).action_assign()
        return picking

    def find_source_dest_location(self):
        dest_location = self.location_id
        # source_location = self.location_src_id
        # fulfiller_warehouse = self.fulfiller_warehouse_id
        requestor_warehouse = self.requestor_warehouse_id
        # if not source_location and fulfiller_warehouse:
        #     if fulfiller_warehouse.reception_steps == 'one_step':
        #         source_location = fulfiller_warehouse.lot_stock_id
        #     else:
        #         source_location = fulfiller_warehouse.wh_input_stock_loc_id
        if not dest_location and requestor_warehouse:
            if requestor_warehouse.reception_steps == 'one_step':
                dest_location = requestor_warehouse.lot_stock_id
            else:
                dest_location = requestor_warehouse.wh_input_stock_loc_id
        return dest_location  # source_location, dest_location

    def create_direct_picking(self):
        destination = self.find_source_dest_location()  # source,
        picking_vals = self.prepare_picking_vals(dest_location_id=destination and destination.id or False
                                                 )  # src_location_id=source and source.id or False
        picking_vals.update({'move_ids_without_package': self.prepare_move_vals()})
        picking = self.env['stock.picking'].create(picking_vals)
        picking.with_company(self.fulfiller_company_id).action_confirm()
        picking.with_company(self.fulfiller_company_id).action_assign()
        return picking

    def create_two_step_pickings(self):
        transit_location = self.get_trasit_location()
        dest_location_id = self.find_source_dest_location()  # src_location_id,
        src_location_id = self.fulfiller_warehouse_id.lot_stock_id.id
        dest_location_id = dest_location_id.id  # self.location_id and self.location_id.id or self.requestor_warehouse_id.lot_stock_id.id
        picking_type_id = self.fulfiller_warehouse_id.int_type_id.id
        partner_id = self.requestor_warehouse_id.partner_id.id

        # Create first piking from Source Location to Transit Location
        picking_vals = self.prepare_picking_vals(src_location_id=src_location_id, dest_location_id=transit_location,
                                                 warehouse=self.fulfiller_warehouse_id)
        picking_vals.update({'move_ids_without_package': self.prepare_move_vals(src_location_id=src_location_id,
                                                                                dest_location_id=transit_location,
                                                                                warehouse=self.fulfiller_warehouse_id,
                                                                                partner_id=partner_id,
                                                                                picking_type_id=picking_type_id)})
        first_picking = self.env['stock.picking'].create(picking_vals)
        first_picking.with_company(self.fulfiller_company_id).action_confirm()
        first_picking.with_company(self.fulfiller_company_id).action_assign()

        # Create second picking from Transit Location to Destination Location
        picking_type_id = self.requestor_warehouse_id.int_type_id.id
        partner_id = self.requestor_warehouse_id.partner_id.id
        picking_vals = self.prepare_picking_vals(src_location_id=transit_location, dest_location_id=dest_location_id,
                                                 warehouse=self.requestor_warehouse_id, partner_id=partner_id,
                                                 picking_type_id=picking_type_id)
        second_picking = self.env['stock.picking'].create(picking_vals)
        for move in first_picking.move_ids_without_package:
            new_move = move.copy({
                'name': move.name,
                'location_id': transit_location,
                'location_dest_id': dest_location_id,
                'picking_type_id': picking_type_id,
                'move_orig_ids': [(6, 0, [move.id])],
                'picking_id': second_picking.id,
                'state': 'waiting',
            })
        return True

    def create_two_step_reverse_pickings(self):
        transit_location = self.get_trasit_location()
        dest_location_id = self.fulfiller_warehouse_id.lot_stock_id.id
        src_location_id = self.requestor_warehouse_id.lot_stock_id.id
        picking_type_id = self.requestor_warehouse_id.int_type_id.id
        partner_id = self.fulfiller_warehouse_id.partner_id.id
        # Create first piking from Source Location to Transit Location
        picking_vals = self.prepare_picking_vals(src_location_id=src_location_id, dest_location_id=transit_location,
                                                 warehouse=self.requestor_warehouse_id, partner_id=partner_id,picking_type_id=picking_type_id)
        picking_vals.update({'move_ids_without_package': self.prepare_move_vals(src_location_id=src_location_id,
                                                                                dest_location_id=transit_location,
                                                                                warehouse=self.requestor_warehouse_id,
                                                                                partner_id=partner_id)})
        first_picking = self.env['stock.picking'].create(picking_vals)
        first_picking.with_company(self.fulfiller_company_id).action_confirm()
        first_picking.with_company(self.fulfiller_company_id).action_assign()

        # Create second picking from Transit Location to Destination Location
        picking_type_id = self.fulfiller_warehouse_id.int_type_id.id
        partner_id = self.fulfiller_warehouse_id.partner_id.id
        picking_vals = self.prepare_picking_vals(src_location_id=transit_location, dest_location_id=dest_location_id,
                                                 warehouse=self.fulfiller_warehouse_id, partner_id=partner_id, picking_type_id=picking_type_id)
        second_picking = self.env['stock.picking'].create(picking_vals)
        for move in first_picking.move_ids_without_package:
            new_move = move.copy({
                'name': move.name,
                'location_id': transit_location,
                'location_dest_id': dest_location_id,
                'picking_type_id': self.fulfiller_warehouse_id.int_type_id.id,
                'move_orig_ids': [(6, 0, [move.id])],
                'picking_id': second_picking.id,
                'state': 'waiting',
            })
        return True

    def action_validate_intercompany_transfer(self):
        if not self.intercompany_transfer_line_ids:
            raise ValidationError(_("Please add any product to do a transfer."))
        for ict in self:
            if ict.state != 'draft':
                return False

            # Checked Indian Accounting is installed or not, based on that we are checking GST Treatment field in the
            # partner is filled or not.
            fulfiller_partner_id = ict.fulfiller_partner_id
            if self.env['ir.module.module'].sudo().search([('name', '=', 'l10n_in'), ('state', '=', 'installed')],
                                                          limit=1) \
                    and fulfiller_partner_id and fulfiller_partner_id.country_id and fulfiller_partner_id.country_id.code == 'IN':
                ict.check_partner_gst_treatment()

            sale_order = ict.create_sale_order()
            purchase_order = ict.create_purchase_order()

            # call autoworkflow method
            ict.execute_workflow()

            # If all operation completed then change the document state
            ict.state = "in_progress"
        return True

    def check_partner_gst_treatment(self):
        """
        Added by Udit
        This method will check GST Treatment field of the partner, if it is not set then
        system will raise a Warning message.
        :return: System will raise a Warning if GST Treatment field is not set in the partner.
        """
        self.ensure_one()
        fulfilment_partner = self.fulfiller_partner_id
        if fulfilment_partner and not fulfilment_partner.l10n_in_gst_treatment:
            raise ValidationError('It seems like GST Treatment is missing in the Vendor of this ICT Fulfiller, '
                                  'please fill it and then try to validate this ICT.')

    def create_sale_order(self):
        so_line_vals = self.prepare_sale_order_line_vals()
        fpos = self.intercompany_channel_id.requestor_fiscal_position_id and self.intercompany_channel_id.requestor_fiscal_position_id or False
        if not fpos:
            fpos = self.env['account.fiscal.position'].with_company(self.fulfiller_company_id)._get_fiscal_position(
                self.requestor_partner_id) or False

        team_id = self.intercompany_channel_id.sales_team_id and self.intercompany_channel_id.sales_team_id or \
                  self.env['crm.team'].with_context(
                      default_team_id=self.requestor_partner_id.team_id.id)._get_default_team_id(
                      domain=['|', ('company_id', '=', self.fulfiller_company_id.id), ('company_id', '=', False)],
                      user_id=self.env.user.id)
        so_vals = {
            'company_id': self.fulfiller_company_id.id,
            # 'warehouse_id' : self.fulfiller_warehouse_id.id,
            'partner_id': self.requestor_partner_id.id,
            # 'l10n_in_gst_treatment' : l10n_in_gst_treatment,
            'user_id': self.env.user.id,
            'intercompany_transfer_id': self.id,
            'order_line': so_line_vals,
            'fiscal_position_id': fpos.id if fpos else False,
            'intercompany_channel_id': self.intercompany_channel_id.id,
            'team_id': team_id and team_id.id or False,
            'pricelist_id': self.pricelist_id.id
        }

        order = self.env['sale.order'].with_user(self.ict_user_id).with_company(self.fulfiller_company_id).create(
            so_vals)
        # order._onchange_company_id()
        order._compute_warehouse_id()
        # order.onchange_partner_id()
        order.write({'payment_term_id': self.origin_order_id.payment_term_id.id,
                     'pricelist_id': self.pricelist_id.id,
                     'team_id': team_id.id})

        # if not order.fiscal_position_id:
        #     order.onchange_partner_shipping_id()
        # order.onchange_user_id()
        if not order.fiscal_position_id:
            order._compute_fiscal_position_id()
        order._compute_team_id()
        if not order.fiscal_position_id and self.intercompany_channel_id and self.intercompany_channel_id.requestor_fiscal_position_id:
            order.fiscal_position_id = self.intercompany_channel_id.requestor_fiscal_position_id.id

        order.warehouse_id = self.fulfiller_warehouse_id.id
        return order

    def prepare_sale_order_line_vals(self):
        # so_line_vals could be [(0,0, dict),(0,0,dict)]
        so_line_vals = []
        partner = self.requestor_partner_id
        for ict_line in self.intercompany_transfer_line_ids:
            product_lang = ict_line.product_id.with_prefetch().with_context(
                lang=partner.lang,
                partner_id=partner.id,
            )
            name = product_lang.display_name
            if product_lang.description_sale:
                name += '\n' + product_lang.description_sale
            so_line_vals.append((0, 0, {
                'name': name,
                'product_id': ict_line.product_id.id,
                'product_uom_qty': ict_line.quantity,
                'product_uom': ict_line.product_uom_id.id,
                'product_packaging_qty': ict_line.product_packaging_qty,
                'product_packaging_id': ict_line.product_packaging_id.id,
                'price_unit': ict_line.unit_price,
            }))
        return so_line_vals

    def _get_date_planned(self, partner_id, product_id, product_qty, start_date):
        days = self.requestor_company_id.po_lead or 0
        days += product_id._select_seller(
            partner_id=partner_id,
            quantity=product_qty,
            date=fields.Date.context_today(self, start_date),
            uom_id=product_id.uom_po_id).delay or 0.0
        date_planned = start_date + relativedelta.relativedelta(days=days)
        return date_planned.strftime(DEFAULT_SERVER_DATETIME_FORMAT)

    def create_purchase_order(self):
        """ Create a purchase order for Inter company
        """
        origins = self.name
        partner = self.fulfiller_partner_id
        # l10n_in_gst_treatment = partner.l10n_in_gst_treatment
        purchase_date = datetime.today()
        fiscal_obj = self.env['account.fiscal.position'].sudo()
        fpos = fiscal_obj.with_company(self.requestor_company_id)._get_fiscal_position(partner) or False
        if not fpos:
            fpos = self.intercompany_channel_id and self.intercompany_channel_id.fulfiller_fiscal_position_id or False
        order_line_vals = self._prepare_purchase_order_line_vals(fpos)
        dates = [fields.Datetime.from_string(value[2]['date_planned']) for value in order_line_vals]
        procurement_date_planned = dates and max(dates) or False
        vals = {
            'partner_id': partner.id,
            # 'l10n_in_gst_treatment': l10n_in_gst_treatment,
            'user_id': self.ict_user_id and self.ict_user_id.id or self.env.user.id,
            'picking_type_id': self.requestor_warehouse_id.in_type_id.id,
            'company_id': self.requestor_company_id.id,
            'currency_id': partner.with_company(self.fulfiller_company_id).property_purchase_currency_id.id or self.fulfiller_company_id.currency_id.id,
                # partner.with_company(
                # self.requestor_company_id).property_purchase_currency_id.id or self.requestor_company_id.currency_id.id,
            'origin': origins,
            'payment_term_id': partner.with_company(self.requestor_company_id).property_supplier_payment_term_id.id,
            'date_order': purchase_date,
            'fiscal_position_id': fpos.id if fpos else False,
            'order_line': order_line_vals,
            'intercompany_transfer_id': self.id,
            'date_planned': procurement_date_planned,
            # 'l10n_in_gst_treatment' : partner.l10n_in_gst_treatment or ''
        }
        return self.env['purchase.order'].with_user(self.ict_user_id).with_company(self.requestor_company_id).create(
            vals)

    def _prepare_purchase_order_line_vals(self, fpos):
        # po_line_vals could be [(0,0, dict),(0,0,dict)]
        partner = self.fulfiller_partner_id
        po_line_vals = []

        for ict_line in self.intercompany_transfer_line_ids:
            date_planned = self._get_date_planned(partner, ict_line.product_id, ict_line.quantity, datetime.today())
            product_lang = ict_line.product_id.with_prefetch().with_context(
                lang=partner.lang,
                partner_id=partner.id,
            )
            name = product_lang.display_name
            if product_lang.description_purchase:
                name += '\n' + product_lang.description_purchase
            taxes = ict_line.product_id.supplier_taxes_id
            taxes_id = fpos.map_tax(taxes) if fpos else taxes
            if taxes_id:
                taxes_id = taxes_id.filtered(lambda x: x.company_id.id == self.requestor_company_id.id)

            po_line_vals.append((0, 0, {
                'name': name,
                'product_id': ict_line.product_id.id,
                'product_qty': ict_line.quantity,
                'price_unit': ict_line.unit_price,
                'product_uom': ict_line.product_uom_id.id,
                'product_packaging_qty': ict_line.product_packaging_qty,
                'product_packaging_id': ict_line.product_packaging_id.id,
                'date_planned': date_planned,
                'taxes_id': [(6, 0, taxes_id.ids)],
            }))
        return po_line_vals

    def action_validate_ict_so_po(self):
        po_context = {'default_company_id': self.requestor_company_id.id, }
        so_context = {'default_type': 'out_invoice',
                      'default_company_id': self.fulfiller_company_id.id,
                      }
        self.sale_ids.with_company(self.fulfiller_company_id).with_user(self.ict_user_id).with_context(
            so_context).filtered(lambda order: order.state in ('draft', 'sent')).action_confirm()
        self.purchase_ids.with_company(self.requestor_company_id).with_user(self.ict_user_id).with_context(
            po_context).filtered(lambda order: order.state in ('draft', 'sent')).button_confirm()
        return True

    def action_create_ict_invoices(self):
        so_context = {'default_move_type': 'out_invoice',
                      'default_company_id': self.fulfiller_company_id.id,
                      }
        channel_customer_invoice_journal = self.intercompany_channel_id and self.intercompany_channel_id.customer_invoice_journal_id and self.intercompany_channel_id.customer_invoice_journal_id.id or False
        if channel_customer_invoice_journal:
            so_context.update({'default_journal_id': channel_customer_invoice_journal})
        ci_process = False
        if len(self.sale_ids.mapped('order_line').filtered(lambda x: x.product_id.invoice_policy == 'delivery')) > 0:
            if len(self.sale_ids.picking_ids.filtered(lambda x: x.state != 'done')) == 0:
                ci_process = True
        else:
            ci_process = True

        if ci_process and len(self.sale_ids.filtered(lambda x: x.invoice_status == 'to invoice')) > 0:
            self.sale_ids.with_company(self.fulfiller_company_id).with_context(so_context)._create_invoices()
            self.invoice_ids.mapped('date') and self.invoice_ids.write(
                {'invoice_date': self.invoice_ids.mapped('date')[0]})

        vb_process = False
        if len(self.purchase_ids.mapped('order_line').filtered(
                lambda x: x.product_id.purchase_method == 'receive')) > 0:
            if len(self.purchase_ids.picking_ids.filtered(lambda x: x.state != 'done')) == 0:
                vb_process = True
        else:
            vb_process = True

        if vb_process and len(self.purchase_ids.filtered(lambda x: x.invoice_status == 'to invoice')) > 0:
            po_context = {'default_move_type': 'in_invoice',
                          'default_company_id': self.requestor_company_id.id,
                          'default_intercompany_transfer_id': self.id,
                          }
            channel_vendor_bill_journal = self.intercompany_channel_id and self.intercompany_channel_id.vendor_bill_journal_id \
                                          and self.intercompany_channel_id.vendor_bill_journal_id.id or False
            if channel_vendor_bill_journal:
                po_context.update({'default_journal_id': channel_vendor_bill_journal})
            self.purchase_ids.with_company(self.requestor_company_id).with_context(po_context).action_create_invoice()
            self.invoice_ids.mapped('date') and self.invoice_ids.write(
                {'invoice_date': self.invoice_ids.mapped('date')[0]})
        return True

    def action_validate_ict_invoices(self):
        # This is the case while ICT Auto workflow executed
        # Vendor bill policy mostly based on received qty
        # That's why when you will create vendor bill for purchase order it will be created with 0.00
        # Becuase while creating vendor bill, incoming shipment isn't received in ICT
        # So ignore invoices with 0 value otherwise those will be paid
        # Vendor bill will be created through the cron of ICT auto workflow.
        # When incoming shipment will be done
        # cron will execute based on regular interval and vendor bill will be created with proper value.
        invoices = self.invoice_ids
        if invoices:
            in_invoices = invoices.filtered(lambda
                                                invoice: invoice.move_type == 'in_invoice' and invoice.amount_total >= 1 and invoice.state not in (
                'posted'))
            in_invoices and in_invoices.action_post()
            out_invoices = invoices.filtered(lambda
                                                 invoice: invoice.move_type == 'out_invoice' and invoice.amount_total >= 1 and invoice.state not in (
                'posted'))
            out_invoices and out_invoices.action_post()

    def action_cancel(self):
        for rec in self:
            msg = ""
            # reverse_transfer = False
            # reverse_ict = False
            # reverse_iwt = False
            # if rec.transfer_type == 'reverse_transfer':
            #     reverse_transfer = True
            if rec.transfer_type == 'inter_company':
                sale = 'done' in rec.sale_ids.picking_ids.mapped('state')
                purchase = 'done' in rec.purchase_ids.picking_ids.mapped('state')
                if sale or purchase:
                    msg = "[%s] You can't cancel validated inter company transaction!!!" % (rec.name)
                else:
                    rec.sale_ids.filtered(lambda x: x.state != 'cancel')._action_cancel()
                    rec.purchase_ids.filtered(lambda x: x.state != 'cancel').button_cancel()
            elif rec.transfer_type == 'inter_warehouse':
                pickings = 'done' in rec.picking_ids.mapped('state')
                if pickings:
                    msg = "[%s] You can't cancel validated inter warehouse transaction!!!" % (rec.name)
                else:
                    rec.picking_ids.filtered(lambda x: x.state != 'cancel').action_cancel()
            else:
                if rec.state != 'draft':
                    msg = "[%s] You can't cancel validated inter company transaction!!!" % (rec.name)
            if msg:
                raise UserError(msg)
            rec.state = "cancel"
        return True

    def action_view_sale(self):
        action = self.env.ref('sale.action_quotations').sudo().read()[0]
        sales = self.mapped('sale_ids')
        if len(sales) > 1:
            action['domain'] = [('id', 'in', sales.ids)]
        elif sales:
            form_view = [(self.env.ref('sale.view_order_form').id, 'form')]
            if 'views' in action:
                action['views'] = form_view + [(state, view) for state, view in action['views'] if view != 'form']
            else:
                action['views'] = form_view
            action['res_id'] = sales.id
        return action

    def action_view_purchase(self):
        action = self.env.ref('purchase.purchase_form_action').sudo().read()[0]
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

    def action_view_delivery(self):
        '''
        This function returns an action that display existing delivery orders
        of given sales order ids. It can either be a in a list or in a form
        view, if there is only one delivery order to show.
        '''
        action = self.env.ref('stock.action_picking_tree_all').sudo().read()[0]

        pickings = self.mapped('picking_ids')
        if len(pickings) > 1:
            action['domain'] = [('id', 'in', pickings.ids)]
        elif pickings:
            form_view = [(self.env.ref('stock.view_picking_form').id, 'form')]
            if 'views' in action:
                action['views'] = form_view + [(state, view) for state, view in action['views'] if view != 'form']
            else:
                action['views'] = form_view
            action['res_id'] = pickings.id

        return action

    def action_view_invoice(self):
        invoices = self.mapped('invoice_ids')
        action = self.env.ref('setu_intercompany_transaction.action_move_invoice').sudo().read()[0]
        if len(invoices) > 1:
            action['domain'] = [('id', 'in', invoices.ids)]
        elif len(invoices) == 1:
            form_view = [(self.env.ref('account.view_move_form').id, 'form')]
            if 'views' in action:
                action['views'] = form_view + [(state, view) for state, view in action['views'] if view != 'form']
            else:
                action['views'] = form_view
            action['res_id'] = invoices.id
        else:
            action = {'type': 'ir.actions.act_window_close'}
        return action

    def execute_workflow(self):
        if not self.auto_workflow_id:
            return

        if self.auto_workflow_id.validate_ict_so_po:
            self.action_validate_ict_so_po()
        if self.auto_workflow_id.create_ict_invoices:
            self.action_create_ict_invoices()
        if self.auto_workflow_id.validate_ict_invoices:
            self.action_validate_ict_invoices()
        return True

    def action_import_ict_lines(self):
        wizard = self.env['wizard.import.ict.product'].with_context({'transfer_type': self.transfer_type}).wizard_view()
        return wizard

class SetuInterCompanyTransferLine(models.Model):
    _name = 'setu.intercompany.transfer.line'
    _description = """
    this is to define how many products will be going to transfer to another warehouse with which price. 
    """
    product_id = fields.Many2one('product.product', "Product")
    quantity = fields.Float(string="Quantity", compute='_compute_product_uom_qty', digits='Product Unit of Measure',
                            default=1.0,store=True, readonly=False, required=True, precompute=True)
    unit_price = fields.Float("Price")
    product_uom_category_id = fields.Many2one(related='product_id.uom_id.category_id', depends=['product_id'])
    product_uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string="Unit of Measure",
        compute='_compute_product_uom',
        store=True, readonly=False, precompute=True, ondelete='restrict')
    intercompany_transfer_id = fields.Many2one("setu.intercompany.transfer", "Inter Company Transfer", index=True)
    product_packaging_id = fields.Many2one(
        comodel_name='product.packaging',
        string="Packaging",
        compute='_compute_product_packaging_id',
        store=True, readonly=False, precompute=True,
        domain="[('sales', '=', True), ('product_id','=',product_id)]")
    product_packaging_qty = fields.Float(
        string="Packaging Quantity",
        compute='_compute_product_packaging_qty',
        store=True, readonly=False, precompute=True)

    @api.depends('product_id', 'product_packaging_qty')
    def _compute_product_uom_qty(self):
        for line in self:
            line.quantity = 0.0

            if not line.product_packaging_id:
                continue
            packaging_uom = line.product_packaging_id.product_uom_id
            qty_per_packaging = line.product_packaging_id.qty
            product_uom_qty = packaging_uom._compute_quantity(
                line.product_packaging_qty * qty_per_packaging, line.product_uom_id)
            if float_compare(product_uom_qty, line.quantity, precision_rounding=line.product_uom_id.rounding) != 0:
                line.quantity = product_uom_qty

    @api.constrains('quantity')
    def _check_quantity(self):
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError(_("Quantity should be greater than 0 to do a transfer."))

    @api.onchange('product_id')
    def product_id_change(self):
        for record in self:
            if not record.product_id:
                return
            # product = record.product_id.with_context(
            #         lang=record.intercompany_transfer_id.fulfiller_partner_id.lang,
            #         partner=record.intercompany_transfer_id.requestor_partner_id,
            #         pricelist=record.intercompany_transfer_id.pricelist_id.id
            # )
            if record.intercompany_transfer_id and record.intercompany_transfer_id.pricelist_id and record.intercompany_transfer_id.requestor_partner_id:
                record.unit_price = record.get_price()

    def get_price(self):
        """
        Added method _get_product_price_rule() during migration from odoo version15 to version16
        """
        product_context = dict(self.env.context, partner_id=self.intercompany_transfer_id.requestor_partner_id.id,
                               date=self.intercompany_transfer_id.ict_date)
        final_price, rule_id = self.intercompany_transfer_id.pricelist_id.with_context(
            product_context)._get_product_price_rule(self.product_id, self.quantity or 1.0)

        return final_price

    @api.depends('product_id')
    def _compute_product_uom(self):
        for line in self:
            if not line.product_uom_id or (line.product_id.uom_id.id != line.product_uom_id.id):
                line.product_uom_id = line.product_id.uom_id

    @api.depends('product_id', 'quantity', 'product_uom_id')
    def _compute_product_packaging_id(self):
        for line in self:
            # remove packaging if not match the product
            if line.product_packaging_id.product_id != line.product_id:
                line.product_packaging_id = False
            # suggest biggest suitable packaging matching the SO's company
            if line.product_id and line.quantity and line.product_uom_id:
                suggested_packaging = line.product_id.packaging_ids \
                    .filtered(lambda p: p.sales and (p.product_id.company_id <= p.company_id <= self.env.company)) \
                    ._find_suitable_product_packaging(line.quantity, line.product_uom_id)
                line.product_packaging_id = suggested_packaging or line.product_packaging_id

    @api.depends('product_packaging_id', 'product_uom_id', 'quantity')
    def _compute_product_packaging_qty(self):
        self.product_packaging_qty = 0
        for line in self:
            if not line.product_packaging_id:
                continue
            line.product_packaging_qty = line.product_packaging_id._compute_qty(line.quantity, line.product_uom_id)

    @api.onchange('product_packaging_id')
    def _onchange_product_packaging_id(self):
        if self.product_packaging_id and self.quantity:
            newqty = self.product_packaging_id._check_qty(self.quantity, self.product_uom_id, "UP")
            if float_compare(newqty, self.quantity, precision_rounding=self.product_uom_id.rounding) != 0:
                return {
                    'warning': {
                        'title': _('Warning'),
                        'message': _(
                            "This product is packaged by %(pack_size).2f %(pack_name)s. You should transfer %(quantity).2f %(unit)s.",
                            pack_size=self.product_packaging_id.qty,
                            pack_name=self.product_id.uom_id.name,
                            quantity=newqty,
                            unit=self.product_uom_id.name
                        ),
                    },
                }
