from odoo import fields, models, api, _
from datetime import datetime


class SetuInterwarehouseChannel(models.Model):
    _name = 'setu.interwarehouse.channel'
    _description = """
        Interwarehouse channel is used to define an automated actions should be taken when destination warehouse receive orders
    """
    name = fields.Char("Name")
    requestor_warehouse_id = fields.Many2one("stock.warehouse", "Requestor Warehouse", change_default=True)
    requestor_company_id = fields.Many2one("res.company", "Requestor", change_default=True)
    fulfiller_company_id = fields.Many2one("res.company", "Fulfiller", change_default=True)
    fulfiller_warehouse_id = fields.Many2one("stock.warehouse", "Fulfiller Warehouse", change_default=True)
    active = fields.Boolean("Active", default=True)
    auto_workflow_id = fields.Many2one("setu.ict.auto.workflow", "Auto workflow")
    ict_user_id = fields.Many2one("res.users", "Inter Company User")
    sequence = fields.Integer("Priority")
    transfer_with_single_picking = fields.Boolean("Direct transfer to destination without transit location?", help="""
            This option is useful to transfer stock between two warehouses directly without moving stock to transit location.
            By default stock will be transferred in two step
                1. source Location to Transit Location
                2. Transit Location to Destination Location
        """)
    validate_ict = fields.Boolean("Auto validate Interwarehouse tansfer record?", default=False)
    location_id = fields.Many2one("stock.location", string="Destination location",
                                  help="IWT will be created for this location from the fulfiller warehouse.")
    locations_ids = fields.Many2many('stock.location', string='Locations', compute='_compute_locations_id', store=True)

    # location_src_id = fields.Many2one("stock.location", string="Source location",
    #                               help="IWT will be created from this location to the requestor warehouse.")

    @api.onchange('fulfiller_warehouse_id')
    def onchange_fulfiller_warehouse_id(self):
        if self.fulfiller_warehouse_id:
            self.fulfiller_company_id = self.fulfiller_warehouse_id.company_id.id
        #     view_location_id = self.fulfiller_warehouse_id.view_location_id
        #     if view_location_id:
        #         locations = self.env['stock.location'].sudo().search(
        #             [('parent_path', 'ilike', '%%/%d/%%' % view_location_id.id),
        #              ('usage', '=', 'internal')])
        #         if locations:
        #             return {'domain': {'location_src_id': [('id', 'in', locations.ids)]}}
        # return {'domain': {'location_src_id': [('id', 'in', [])]}}

    # @api.onchange('fulfiller_warehouse_id')
    # def onchange_fulfiller_warehouse_id(self):
    #     if self.fulfiller_warehouse_id:
    #         self.fulfiller_company_id = self.fulfiller_warehouse_id.company_id.id

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
            self.requestor_company_id = self.requestor_warehouse_id.company_id.id
            self.fulfiller_company_id = False
            self.fulfiller_warehouse_id = False
        #     self.location_id = False
        #     view_location_id = self.requestor_warehouse_id.view_location_id
        #     if view_location_id:
        #         locations = self.env['stock.location'].sudo().search(
        #             [('parent_path', 'ilike', '%%/%d/%%' % view_location_id.id),
        #              ('usage', '=', 'internal')])
        #         if locations:
        #             return {'domain': {'location_id': [('id', 'in', locations.ids)]}}
        # return {'domain': {'location_id': [('id', 'in', [])]}}

    def get_channel_source_for_internal_transfer(self, requestor_warehouse_id, all_channel=False):
        if not all_channel:
            channel = self.search([('requestor_warehouse_id', '=', requestor_warehouse_id)], order='sequence', limit=1)
            return channel or False
        else:
            channel = self.search([('requestor_warehouse_id', '=', requestor_warehouse_id)], order='sequence')
            return channel or False

    def prepare_ict_line_vals(self, order_line, ict, remaining_qty=0.0):
        return {
            'product_id': order_line.product_id.id,
            'quantity': remaining_qty or order_line.product_uom_qty,
            'unit_price': order_line.price_unit,
            'intercompany_transfer_id': ict.id,
        }

    def create_ict_lines(self, origin_sale_id, ict):
        ict_lines = []
        for line in origin_sale_id.order_line.filtered(lambda line: not line.route_id):
            ict_line_vals = self.prepare_ict_line_vals(line, ict)
            ict_line = self.env['setu.intercompany.transfer.line'].create(ict_line_vals)
            ict_lines.append(ict_line)
        return ict_lines

    def create_ict_lines_for_multiple_iwt(self, origin_sale_id, ict, remaining_product_dict={}):
        ict_lines = []
        product_dict = remaining_product_dict.copy()
        for key, val in product_dict.items():
            product = self.env['product.product'].browse(key)

            remaining_qty = remaining_product_dict.get(key, 0)
            if not remaining_qty:
                continue
            wh_available_stock = product.with_context({'warehouse': self.fulfiller_warehouse_id.id}).qty_available
            wh_outgoing_stock = product.with_context({'warehouse': self.fulfiller_warehouse_id.id}).outgoing_qty
            net_on_hand = wh_available_stock - wh_outgoing_stock
            if net_on_hand <= 0.0:
                net_on_hand = 0.0
            if not net_on_hand:
                continue
            order_qty = remaining_qty
            if net_on_hand < remaining_qty:
                order_qty = net_on_hand
                remaining_product_dict.update(
                    {product.id: remaining_qty - order_qty if net_on_hand < remaining_qty else 0})
            else:
                remaining_product_dict.pop(product.id)
            order_line = origin_sale_id.order_line.filtered(
                lambda x: x.product_id == product) if origin_sale_id else False
            ict_line_vals = {
                'product_id': product.id,
                'quantity': order_qty,
                'intercompany_transfer_id': ict.id,
                'product_packaging_id': order_line.product_packaging_id.id,
                'product_uom_id': order_line.product_uom.id,
                'product_packaging_qty': order_line.product_packaging_qty,
            }
            ict_line = self.env['setu.intercompany.transfer.line'].create(ict_line_vals)
            ict_lines.append(ict_line)
        return ict_lines

    def prepare_interwarehouse_vals(self, origin_sale_id):
        ict_vals = {
            'ict_date': datetime.today(),
            'requestor_warehouse_id': origin_sale_id.warehouse_id.id,
            'fulfiller_warehouse_id': self.fulfiller_warehouse_id.id,
            'interwarehouse_channel_id': self.id,
            'ict_user_id': self.ict_user_id.id,
            'origin_order_id': origin_sale_id.id,
            'transfer_type': 'inter_warehouse',
            'state': 'draft',
            'transfer_with_single_picking': self.transfer_with_single_picking,
            'location_id': self.location_id and self.location_id.id or False,
            # 'location_src_id': self.location_src_id and self.location_src_id.id or False
        }
        return ict_vals

    def create_iwt_from_multiple_channels(self, origin_sale_id, remaining_product_dict={}):
        ict_vals = self.prepare_interwarehouse_vals(origin_sale_id)
        ict = self.env['setu.intercompany.transfer'].create(ict_vals)
        ict_lines = self.create_ict_lines_for_multiple_iwt(origin_sale_id, ict,
                                                           remaining_product_dict=remaining_product_dict)
        if not ict_lines:
            ict.sudo().unlink()
            return
        ict.onchange_requestor_warehouse_id()
        ict.onchange_fulfiller_warehouse_id()
        if self.location_id:
            ict.location_id = self.location_id.id
        if ict.state == 'draft' and self.validate_ict:
            ict.action_validate_internal_transfer()
        return ict

    def create_iwt_from_channel(self, origin_sale_id):
        ict_vals = self.prepare_interwarehouse_vals(origin_sale_id)
        ict = self.env['setu.intercompany.transfer'].create(ict_vals)
        ict_lines = self.create_ict_lines(origin_sale_id, ict)
        ict.onchange_requestor_warehouse_id()
        ict.onchange_fulfiller_warehouse_id()
        if self.location_id:
            ict.location_id = self.location_id.id
        if ict.state == 'draft' and self.validate_ict:
            ict.action_validate_internal_transfer()
        return ict

    # def create_ict_lines_from_order_lines(self, origin_sale_id, ict):
    #     ict_lines = []
    #     for line in origin_sale_id.order_line:
    #         ict_line_vals = self.prepare_ict_line_vals(line, ict)
    #         ict_line = self.env['setu.intercompany.transfer.line'].create(ict_line_vals)
    #         ict_lines.append(ict_line)
    #     return ict_lines

    def create_iwt_from_multi_channel_of_order_line(self, origin_sale_id, order_lines):
        ict_vals = self.prepare_interwarehouse_vals(origin_sale_id)
        ict = self.env['setu.intercompany.transfer'].create(ict_vals)
        for line in order_lines:
            ict_line_vals = self.prepare_ict_line_vals(line, ict)
            ict_line = self.env['setu.intercompany.transfer.line'].create(ict_line_vals)
        ict.onchange_requestor_warehouse_id()
        ict.onchange_fulfiller_warehouse_id()
        if self.location_id:
            ict.location_id = self.location_id.id
        if ict.state == 'draft' and self.validate_ict:
            ict.action_validate_internal_transfer()
        return ict
