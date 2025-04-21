from odoo import models, fields, api, _
from odoo.exceptions import UserError
from markupsafe import Markup


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def default_get(self, fields):
        res = super().default_get(fields)
        if 'company_id' in res and res['company_id']:
            company_id = self.env['res.company'].sudo().browse(res['company_id'])
            res['distributed_replenish'] = company_id.distributed_iwt
        return res

    stock_replenishment_priority = fields.Selection(related='company_id.stock_replenishment_priority', readonly=True)
    intercompany_transfer_id = fields.Many2one("setu.intercompany.transfer", "Intercompany Transfer", copy=False,
                                               index=True)
    create_ict_option = fields.Selection(related='company_id.create_ict_option', readonly=True)
    create_iwt_option = fields.Selection(related='company_id.create_iwt_option', readonly=True)
    distributed_iwt = fields.Boolean(related='company_id.distributed_iwt')
    intercompany_channel_id = fields.Many2one("setu.intercompany.channel", "Intercompany Channel", copy=False,
                                              index=True)
    interwarehouse_channel_id = fields.Many2one("setu.interwarehouse.channel", "Interwarehouse Channel", copy=False,
                                                index=True)
    interwarehouse_channel_ids = fields.Many2many("setu.interwarehouse.channel", string="Interwarehouse Channels",
                                                  copy=False)
    intercompany_channel_ids = fields.Many2many("setu.intercompany.channel", string="InterCompany Channels",
                                                copy=False)
    ict_ids = fields.One2many('setu.intercompany.transfer', 'origin_order_id', string='ICT')
    ict_count = fields.Integer(string='ICT', compute='_compute_ict_ids')
    ict_transfer_type = fields.Selection(string="ICT Transfer Type",
                                         related="ict_ids.transfer_type")
    distributed_replenish = fields.Boolean(string="Distributed IWT?", copy=False)
    sale_iwt_option = fields.Selection(
        [('as_per_company', 'As Per Company'),
         ('stock_plus_interwarehouse', 'First use available stock and create inter warehouse transfer for remaining'),
         ('always', 'Always replenish stock(Use Stock From Other Warehouses)'),
         ('manual', 'Manual - Select Inter Warehouse Channel manually in sale order'),
         ], "Create Inter Warhouse Transfer", help="""
               this field is useful to control when the inter warehouse record will be created automatically 
               1. Always create interwarehouse record when sale order gets confirmed in requestor warehouse
               2. Manual - provide an option to select inter warehouse channel manual in sale order
               """, default='as_per_company')

    @api.onchange('sale_iwt_option')
    def _onchange_sale_iwt_option(self):
        if self.sale_iwt_option != 'manual':
            self.unset_iwt_reference()

    def unset_iwt_reference(self):
        for rec in self:
            rec.interwarehouse_channel_id = False
            rec.intercompany_channel_id = False
            rec.order_line.interwarehouse_channel_id = False

    @api.onchange('interwarehouse_channel_id')
    def onchange_interwarehouse_channel(self):
        if self.interwarehouse_channel_id:
            for lines in self.order_line:
                lines.interwarehouse_channel_id = self.interwarehouse_channel_id

    @api.depends('ict_ids')
    def _compute_ict_ids(self):
        for order in self:
            order.ict_count = len(order.ict_ids)

    def action_draft(self):
        orders = self.filtered(lambda s: s.state in ['cancel', 'sent'])
        orders.unset_iwt_reference()
        res = super().action_draft()
        return res

    def _action_cancel(self):
        for rec in self:
            # .filtered(lambda x:x.state not in ['draft', 'cancel', 'sent'])
            ict_ids = rec.ict_ids.filtered(lambda x: x.state != 'cancel')
            ict_ids.action_cancel()
        return super()._action_cancel()

    def _prepare_invoice(self):
        vals = super(SaleOrder, self)._prepare_invoice()
        vals.update({'intercompany_transfer_id': self.intercompany_transfer_id.id})
        return vals

    def enouogh_stock_available(self, single_or_all='check_single'):
        check_single_prod_outofstock = True if single_or_all == 'check_single' else False
        outofstock_counter = 0
        total_lines = len(self.order_line.ids)
        for line in self.order_line:
            stock = line.product_id.with_context({'warehouse': self.warehouse_id.id}).free_qty
            if stock < line.product_uom_qty:
                outofstock_counter = outofstock_counter + 1
            if check_single_prod_outofstock and outofstock_counter > 0:
                return False
            if outofstock_counter == total_lines:
                return False
        return True

    def action_create_intercompany(self):
        if self.intercompany_transfer_id:
            raise UserError(_('Inter company record has been already created.'))
        elif not self.intercompany_channel_id:
            raise UserError(_('Inter company channel must be selected to create inter company record.'))

        for order in self:
            if order.company_id.stock_replenishment_priority == "refill_from_intercomapny" and order.order_line:
                self.check_and_create_ict()
        return True

    def action_create_interwarehouse(self):
        if self.intercompany_transfer_id:
            raise UserError(_('Inter warehouse record has been already created.'))
        elif not self.interwarehouse_channel_id:
            raise UserError(_('Inter warehouse channel must be selected to create inter warehouse record.'))

        for order in self:
            if order.company_id.stock_replenishment_priority == "refill_from_interwarehouse" and order.order_line:
                if (
                        order.create_iwt_option == 'manual' and order.sale_iwt_option == 'as_per_company') or order.sale_iwt_option == 'manual':
                    self.check_and_create_iwt()
        return True

    def action_confirm(self):
        for order in self.filtered(lambda x: not x.intercompany_transfer_id):
            if order.company_id.stock_replenishment_priority == "refill_from_intercomapny":
                self.check_and_create_ict()
            elif order.company_id.stock_replenishment_priority == "refill_from_interwarehouse":
                self.check_and_create_iwt()
            elif order.company_id.stock_replenishment_priority == "do_nothing":
                continue
        res = super(SaleOrder, self).action_confirm()
        return res

    def check_and_create_ict(self):
        create_ict_option = self.company_id.create_ict_option
        if create_ict_option == "manual" and not self.env.context.get('ict_manual', False):
            return True
        if self.env.context.get('ict_manual', False):
            self.create_intercompany_transfer_records()
        if create_ict_option == "stock_plus_intercompany":
            self.create_multi_intercompany_transfer_records()
        if create_ict_option == "always":
            self.create_intercompany_transfer_records()
        if create_ict_option == "insufficient_stock_single_product":
            if not self.enouogh_stock_available("check_single"):
                self.create_intercompany_transfer_records()
        if create_ict_option == "insufficient_stock_all_product":
            if not self.enouogh_stock_available("check_all"):
                self.create_intercompany_transfer_records()
        return True

    def check_and_create_iwt(self):
        create_ict_option = self.company_id.create_iwt_option if self.sale_iwt_option == 'as_per_company' else self.sale_iwt_option
        if create_ict_option == "manual" and not self.env.context.get('iwt_manual', False):
            return True
        if self.env.context.get('iwt_manual', False):
            self.create_interwarehouse_transfer_records()
        if create_ict_option == "stock_plus_interwarehouse":
            self.create_multi_interwarehouse_transfer_records()
        elif create_ict_option == "always":
            if (self.distributed_iwt and self.sale_iwt_option == 'as_per_company') or self.distributed_replenish:
                self.create_multi_interwarehouse_transfer_records()
            else:
                self.create_interwarehouse_transfer_records()
        elif create_ict_option == "insufficient_stock_single_product":
            if not self.enouogh_stock_available("check_single"):
                if self.distributed_iwt and self.sale_iwt_option == 'as_per_company':
                    self.create_multi_interwarehouse_transfer_records()
                else:
                    self.create_interwarehouse_transfer_records()
        elif create_ict_option == "insufficient_stock_all_product":
            if not self.enouogh_stock_available("check_all"):
                if self.distributed_iwt and self.sale_iwt_option == 'as_per_company':
                    self.create_multi_interwarehouse_transfer_records()
                else:
                    self.create_interwarehouse_transfer_records()
        return True

    def create_intercompany_transfer_records(self):
        if self.create_ict_option == "manual":
            channel = self.intercompany_channel_id
        if not self.create_ict_option == "manual":
            channel_env = self.env['setu.intercompany.channel']
            channel = channel_env.get_channel_source_for_ict(self.company_id.id)
        # channel_env = self.env['setu.intercompany.channel']
        # channel = channel_env.get_channel_source_for_ict(self.company_id.id)
        if not channel:
            # Log internal note for sales order
            # ict creation process may have some error, please refer log
            msg = Markup("<b>" + _(
                '%s') + "</b>") % _(
                "Can't create ICT for this order, because ICT channel not found for this company. Create ICT manually.")
            self.message_post(body=msg)
            return False
        self.intercompany_channel_id = channel.id
        return channel.create_ict_from_channel(self)

    def create_multi_intercompany_transfer_records(self):
        channel_env = self.env['setu.intercompany.channel']
        channels = channel_env.get_channel_source_for_ict(self.company_id.id, all_channel=True)
        if not channels:
            # Log internal note for sales order
            # ict creation process may have some error, please refer log
            msg = Markup("<b>" + _(
                '%s') + "</b>") % _(
                "Can't create ICT for this order, because ICT channel not found for this company. Create ICT manually.")
            self.message_post(body=msg)
            return False
        # self.intercompany_channel_id = channel.id

        remaining_product_dict = {}
        sale_order_line_dict = {}
        for line in self.order_line:
            qty = line.product_uom_qty
            product = line.product_id
            if product in sale_order_line_dict:
                product_uom_qty = sale_order_line_dict.get(product)
                sale_order_line_dict.update({product: product_uom_qty + qty})
            else:
                sale_order_line_dict.update({product: qty})

        for product_id, product_uom_qty in sale_order_line_dict.items():
            wh_available, wh_outgoing, net_on_hand = self.get_product_stock(product_id, product_uom_qty)
            if net_on_hand >= product_uom_qty:
                continue

            remaining_product_dict.update({product_id.id: product_uom_qty - (net_on_hand if net_on_hand > 0 else 0)})
        for channel in channels:
            if not remaining_product_dict:
                continue
            channel.create_ict_from_multi_channel(self, remaining_product_dict=remaining_product_dict)
            self.intercompany_channel_ids = [(4, channel.id)]
        # return channel.create_ict_from_multi_channel(self, remaining_product_dict=remaining_product_dict)
        if remaining_product_dict:
            products = self.env['product.product'].browse(remaining_product_dict.keys())
            self.message_post(
                body=Markup('<p style="color:red;">%s %s %s</p>') % (
                    _('Stock of'),
                    _(products.mapped('name')),
                    _('has been not found in any Companies!')))

    def get_product_stock(self, product_id, order_qty):
        wh_available = product_id.with_context({'warehouse': self.warehouse_id.id}).qty_available
        wh_outgoing = product_id.with_context({'warehouse': self.warehouse_id.id}).outgoing_qty
        net_on_hand = wh_available - wh_outgoing
        return wh_available, wh_outgoing, net_on_hand

    def create_multi_interwarehouse_transfer_records(self):
        channel_env = self.env['setu.interwarehouse.channel']
        channels = channel_env.get_channel_source_for_internal_transfer(self.warehouse_id.id, all_channel=True)
        if not channels:
            # Log internal note for sales order
            # ict creation process may have some error, please refer log
            msg = Markup("<b>" + _(
                '%s') + "</b> ") % _(
                "Can't create Inter Warehouse Transfer for this order, because Inter Warehouse Channel not found for "
                "this warehouse. Please create manually.")
            self.message_post(body=msg)
            return False

        ##Find total products and it's qty, write all products & qty in dict
        order_qty_dict = {}
        for line in self.order_line.filtered(lambda line: not line.route_id):
            if line.product_id in order_qty_dict:
                qty = order_qty_dict.get(line.product_id)
                order_qty_dict.update({line.product_id: line.product_uom_qty + qty})
            else:
                order_qty_dict.update({line.product_id: line.product_uom_qty})

        remaining_product_dict = {}
        if self.sale_iwt_option == 'as_per_company' and self.create_iwt_option in ['insufficient_stock_single_product',
                                                                                   'always',
                                                                                   'insufficient_stock_all_product'] or (
                self.sale_iwt_option == 'always' and self.distributed_replenish):

            remaining_product_dict.update(
                dict((product_id.id, product_uom_qty) for (product_id, product_uom_qty) in order_qty_dict.items()))
        else:
            for product_id, product_uom_qty in order_qty_dict.items():
                wh_available, wh_outgoing, net_on_hand = self.get_product_stock(product_id, product_uom_qty)
                if net_on_hand > product_uom_qty:
                    continue
                remaining_product_dict.update(
                    {product_id.id: product_uom_qty - (net_on_hand if net_on_hand > 0 else 0)})

        for channel in channels:
            if not remaining_product_dict:
                continue
            channel.create_iwt_from_multiple_channels(self, remaining_product_dict=remaining_product_dict)
            self.interwarehouse_channel_ids = [(4, channel.id)]
        if remaining_product_dict:
            products = self.env['product.product'].browse(remaining_product_dict.keys())
            self.message_post(
                body=Markup('<p style="color:red;">%s %s %s</p>') % (
                    _('Stock of'),
                    _(products.mapped('name')),
                    _('has been not found in any warehouses!')
                ))

    def create_interwarehouse_transfer_records(self):
        channel = self.env['setu.interwarehouse.channel']
        if self._context.get('iwt_manual', False):
            channel = self.interwarehouse_channel_id

        if not channel:
            channel = channel.get_channel_source_for_internal_transfer(self.warehouse_id.id)
            self.interwarehouse_channel_id = channel and channel.id

        if self._context.get('iwt_manual', False):
            if channel and len(self.order_line.interwarehouse_channel_id) > 1:
                channels = self.order_line.interwarehouse_channel_id
                for channel in channels:
                    lines = self.order_line.filtered(
                        lambda line: line.interwarehouse_channel_id.id == channel.id and not line.route_id)
                    channel.create_iwt_from_multi_channel_of_order_line(self, lines)
                return True

        if not channel:
            # Log internal note for sales order
            # ict creation process may have some error, please refer log
            msg = Markup("<b>" + _(
                '%s') + "</b>") % (
                      "Can't create Inter Warehouse Transfer for this order, because Inter Warehouse Channel not found for this warehouse. Please create manually.")
            self.message_post(body=msg)
            return False
        return channel.create_iwt_from_channel(self)

    def action_view_ict(self):
        # if not self.intercompany_transfer_id and self.interwarehouse_channel_id:
        #     return self.action_view_iwt()
        report_display_views = []
        if self.ict_transfer_type == 'inter_company':
            form_view_id = self.env.ref('setu_intercompany_transaction.setu_intercompany_transfer_form').id
            tree_view_id = self.env.ref('setu_intercompany_transaction.setu_intercompany_transfer_tree').id
            action_name = _('Inter Company Transactions')
        else:
            form_view_id = self.env.ref('setu_intercompany_transaction.setu_interwareouse_transfer_form').id
            tree_view_id = self.env.ref('setu_intercompany_transaction.setu_interwarehouse_transfer_tree').id
            action_name = _('Inter Warehouse Transactions')

        if len(self.ict_ids.ids) > 1:
            report_display_views.append((tree_view_id, 'tree'))
        report_display_views.append((form_view_id, 'form'))

        return {
            'name': action_name,
            'res_model': 'setu.intercompany.transfer',
            'domain': [('id', 'in', self.ict_ids.ids)],
            'res_id': self.ict_ids and self.ict_ids[0].id or False,
            'view_mode': "form",
            'type': 'ir.actions.act_window',
            'views': report_display_views,
        }
