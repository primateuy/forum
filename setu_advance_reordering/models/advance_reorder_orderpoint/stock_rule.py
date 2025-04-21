import logging
from collections import defaultdict
from dateutil.relativedelta import relativedelta
from itertools import groupby
from odoo.addons.stock.models.stock_rule import ProcurementException
from odoo.tools.float_utils import float_compare
from odoo import api, fields, models, _,SUPERUSER_ID
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StockRule(models.Model):
    _inherit = 'stock.rule'

    def find_supplier_info(self, product, partner, company):
        supplier = self.env['product.supplierinfo'].search(
            [('partner_id', '=', partner.id), ('product_tmpl_id', '=', product.product_tmpl_id.id),
             ('product_id', '=', product.id)])
        if not supplier:
            supplier = self.env['product.supplierinfo'].search(
                [('partner_id', '=', partner.id), ('product_tmpl_id', '=', product.product_tmpl_id.id)])
        supplier_with_company = supplier.filtered(lambda x:x.company_id)
        if supplier_with_company and company:
            supplier_company = supplier_with_company.filtered(lambda x:x.company_id == company and x.currency_id == company.currency_id)
        else:
            supplier_company = supplier.filtered(lambda x:x.currency_id == company.currency_id)
        if supplier_company:
            supplier = supplier_company[0]
        else:
            supplier = supplier[0] or supplier
        return supplier

    @api.model
    def _run_buy(self, procurements):
        if not self._context.get('custom_order_point_function', False):
            return super(StockRule, self)._run_buy(procurements)
        procurements_by_po_domain = defaultdict(list)
        errors = []
        for procurement, rule in procurements:
            domain = [('product_id', '=', procurement.product_id.id),
                      ('location_id', '=', procurement.location_id.id), ('trigger', '=', 'auto')]
            order_point = self.env['stock.warehouse.orderpoint'].search(domain, limit=1)
            if not order_point:
                return super(StockRule, self)._run_buy(procurements)
            # Get the schedule date in order to find a valid seller
            # procurement_date_planned = fields.Datetime.from_string(procurement.values['date_planned'])
            # schedule_date = (procurement_date_planned - relativedelta(days=procurement.company_id.po_lead))
            partner = supplier = False
            sory_by = "sequence"
            lead_days = 0
            if order_point.vendor_selection_strategy == "specific_vendor" and order_point.partner_id:
                partner = order_point.partner_id
                supplier = self.find_supplier_info(procurement.product_id, partner, order_point.company_id)
                lead_days = supplier and supplier.delay or 0
            elif order_point.vendor_selection_strategy == "quickest":
                sory_by = "delay"
                lead_days, dummy = rule._get_lead_days(procurement.product_id.with_context(sory_by=sory_by))
                lead_days = 'total_delay' in lead_days and lead_days['total_delay'] or 0
            elif order_point.vendor_selection_strategy == "cheapest":
                sory_by = "price"
                lead_days, dummy = rule._get_lead_days(procurement.product_id.with_context(sory_by=sory_by,
                                                                                           op_company=procurement.company_id))
                lead_days = 'total_delay' in lead_days and lead_days['total_delay'] or 0
            if order_point.vendor_selection_strategy in ['quickest', 'cheapest'] or (
                    order_point.vendor_selection_strategy == 'specific_vendor' and supplier):
                lead_days_date = fields.Datetime.today() + relativedelta(days=lead_days)
                procurement.values.update({'date_planned': lead_days_date,
                                           'date_deadline': lead_days_date})
            procurement_date_planned = fields.Datetime.from_string(procurement.values['date_planned'])
            schedule_date = (procurement_date_planned - relativedelta(days=procurement.company_id.po_lead))
            if not supplier:
                supplier = procurement.product_id.with_context(
                    {'sory_by': sory_by, 'op_company': procurement.company_id})._select_seller(
                    quantity=procurement.product_qty,
                    date=schedule_date.date(),
                    uom_id=procurement.product_uom)
                partner = supplier.partner_id

            if not partner:
                msg = _(
                    'There is no matching vendor price to generate the purchase order for product %s (no vendor '
                    'defined, minimum quantity not reached, dates not valid, ...). Go on the product form and complete '
                    'the list of vendors.') % (
                          procurement.product_id.display_name)
                # raise UserError(msg)
                errors.append((procurement, msg))
            # we put `supplier_info` in values for extensibility purposes
            procurement.values['supplier'] = supplier
            # procurement.values['propagate_date'] = rule.propagate_date
            # procurement.values['propagate_date_minimum_delta'] = rule.propagate_date_minimum_delta
            procurement.values['propagate_cancel'] = rule.propagate_cancel

            domain = rule._make_po_get_domain(procurement.company_id, procurement.values, partner)
            procurements_by_po_domain[domain].append((procurement, rule))

        if errors:
            raise ProcurementException(errors)

        for domain, procurements_rules in procurements_by_po_domain.items():
            # Get the procurements for the current domain.
            # Get the rules for the current domain. Their only use is to create
            # the PO if it does not exist.
            procurements, rules = zip(*procurements_rules)

            # Get the set of procurement origin for the current domain.
            origins = set([p.origin for p in procurements])
            # Check if a PO exists for the current domain.
            po = self.env['purchase.order'].sudo().search([dom for dom in domain], limit=1)
            company_id = procurements[0].company_id
            if not po:
                positive_values = [p.values for p in procurements if
                                   float_compare(p.product_qty, 0.0, precision_rounding=p.product_uom.rounding) >= 0]
                if positive_values:
                    # We need a rule to generate the PO. However the rule generated
                    # the same domain for PO and the _prepare_purchase_order method
                    # should only uses the common rules's fields.
                    vals = rules[0]._prepare_purchase_order(company_id, origins, positive_values)
                    vals.update({'date_order': fields.datetime.today()})
                    # The company_id is the same for all procurements since
                    # _make_po_get_domain add the company in the domain.
                    # We use SUPERUSER_ID since we don't want the current user to be follower of the PO.
                    # Indeed, the current user may be a user without access to Purchase, or even be a portal user.
                    po = self.env['purchase.order'].with_company(company_id).with_user(SUPERUSER_ID).create(vals)
            else:
                # If a purchase order is found, adapt its `origin` field.
                if po.origin:
                    missing_origins = origins - set(po.origin.split(', '))
                    if missing_origins:
                        po.write({'origin': po.origin + ', ' + ', '.join(missing_origins)})
                else:
                    po.write({'origin': ', '.join(origins)})

            procurements_to_merge = self._get_procurements_to_merge(procurements)
            procurements = self._merge_procurements(procurements_to_merge)

            po_lines_by_product = {}
            grouped_po_lines = groupby(
                po.order_line.filtered(lambda l: not l.display_type and l.product_uom == l.product_id.uom_po_id).sorted(
                    'product_id'), key=lambda l: l.product_id.id)
            for product, po_lines in grouped_po_lines:
                po_lines_by_product[product] = self.env['purchase.order.line'].concat(*list(po_lines))
            po_line_values = []
            for procurement in procurements:
                po_lines = po_lines_by_product.get(procurement.product_id.id, self.env['purchase.order.line'])
                po_line = po_lines._find_candidate(*procurement)

                if po_line:
                    # If the procurement can be merge in an existing line. Directly
                    # write the new values on it.
                    vals = self._update_purchase_order_line(procurement.product_id,
                                                            procurement.product_qty, procurement.product_uom,
                                                            company_id,
                                                            procurement.values, po_line)
                    po_line.write(vals)
                else:
                    if float_compare(procurement.product_qty, 0,
                                     precision_rounding=procurement.product_uom.rounding) <= 0:
                        # If procurement contains negative quantity, don't create a new line that would contain negative qty
                        continue
                    # If it does not exist a PO line for current procurement.
                    # Generate the create values for it and add it to a list in
                    # order to create it in batch.
                    partner = procurement.values['supplier'].partner_id
                    po_line_values.append(self.env['purchase.order.line']._prepare_purchase_order_line_from_procurement(
                        procurement.product_id, procurement.product_qty,
                        procurement.product_uom, procurement.company_id,
                        procurement.values, po))
            self.env['purchase.order.line'].sudo().create(po_line_values)

    @api.model
    def _run_ict(self, procurements):
        """
        This method will be called when reordering rules will be triggered, ICT will be created or updated as per the
        data.
        :param procurements: Procurement data.
        """
        channel_env = self.env['setu.intercompany.channel']
        ict_iwt_obj = self.env['setu.intercompany.transfer']
        procurement_dict = self.get_warehouse_wise_procurement(procurements)
        for warehouse, procurements in procurement_dict.items():
            warehouse_id = self.env['stock.warehouse'].sudo().browse(warehouse)
            company = warehouse_id.company_id
            channel = channel_env.get_channel_source_for_ict(company.id)
            ict_lines = self.create_ict_iwt_lines(warehouse_id, channel, procurements, place='ict')
            if ict_lines:
                ict_iwt_domain = self.ict_iwt_search_domain(warehouse_id, channel, place='ict')
                ict = ict_iwt_obj.search(ict_iwt_domain)
                if ict:
                    ict = ict[0]
                    ict.write({'intercompany_transfer_line_ids': ict_lines})
                else:
                    ict_vals = channel.prepare_intercompany_vals_from_adv(warehouse_id, channel, data={})
                    ict_vals.update({'intercompany_transfer_line_ids': ict_lines})
                    ict = self.env['setu.intercompany.transfer'].create(ict_vals)
                ict.onchange_requestor_warehouse_id()
                ict.onchange_fulfiller_warehouse_id()
                ict.intercompany_transfer_line_ids.product_id_change()

    # # Create Inter warehouse Transfer Record (IWT)
    # def _run_iwt(self, procurements):
    #     inter_warehouse_channel_obj = self.env['setu.interwarehouse.channel']
    #     inter_company_transfer_obj = self.env['setu.intercompany.transfer']
    #     inter_warehouse_channel_id = config_id.inter_warehouse_channel_id
    #
    #     iwt_lines = self.create_ict_lines(self.summary_ids, config_id)
    #     if iwt_lines:
    #         iwt_vals = inter_warehouse_channel_obj.prepare_interwarehouse_values(config_id.warehouse_id,
    #                                                                            inter_warehouse_channel_id)
    #         iwt_vals.update({'procurement_warehouse_id': self.id,
    #                          'intercompany_transfer_line_ids': iwt_lines})
    #         iwt = inter_company_transfer_obj.create(iwt_vals)
    #
    #         iwt.onchange_requestor_warehouse_id()
    #         iwt.onchange_fulfiller_warehouse_id()
    #
    #         if iwt.state == 'draft' and inter_warehouse_channel_id.validate_ict:
    #             iwt.action_validate_internal_transfer()
    #     return True

    @api.model
    def _run_iwt(self, procurements):
        """
        This method will be called when reordering rules will be triggered, IWT will be created or updated as per the
        data.
        :param procurements: Procurement data.
        """
        procurement_dict = self.get_warehouse_wise_procurement(procurements)
        for warehouse, procurements in procurement_dict.items():
            warehouse_id = self.env['stock.warehouse'].sudo().browse(warehouse)
            # company = warehouse_id.company_id
            channel_env = self.env['setu.interwarehouse.channel']
            channels = channel_env.get_channel_source_for_internal_transfer(warehouse_id.id, all_channel=True)
            # if not channels:
            #     # Log internal note for sales order
            #     # ict creation process may have some error, please refer log
            #     msg = "<b>" + _(
            #         "Can't create Inter Warehouse Transfer for this order, because Inter Warehouse Channel not found for this warehouse. Please create manually.") + "</b>"
            #     self.message_post(body=msg)
            #     return False

            ##Find total products and it's qty, write all products & qty in dict
            remaining_product_dict = {}
            iwt_ids = []
            for line in procurements:
                # wh_available = line.product_id.with_context({'warehouse' : self.warehouse_id.id}).qty_available
                # wh_outgoing = line.product_id.with_context({'warehouse': self.warehouse_id.id}).outgoing_qty
                # net_on_hand= wh_available - (wh_outgoing - line.product_uom_qty)
                # wh_available, wh_outgoing, net_on_hand = self.get_product_stock(line.product_id, warehouse_id)
                # if net_on_hand < 0.0:
                #     net_on_hand = 0.0
                # if net_on_hand > line.product_uom_qty:
                #     continue

                prod_qty = line.product_qty
                qty = remaining_product_dict.get(line.product_id.id)
                if qty:
                    prod_qty = prod_qty + qty
                    remaining_product_dict.update({line.product_id.id: prod_qty})
                else:
                    remaining_product_dict.update({line.product_id.id: prod_qty})

            for channel in channels:
                if not remaining_product_dict:
                    continue
                remaining_product_dict = self.create_iwt_from_orderpoints(channel, remaining_product_dict)

    def create_iwt_from_orderpoints(self, channel, remaining_product_dict):
        channel_env = self.env['setu.interwarehouse.channel']
        ict_iwt_obj = self.env['setu.intercompany.transfer']
        # channel = channel_env.get_channel_source_for_internal_transfer(warehouse_id.id)
        warehouse_id = channel.requestor_warehouse_id
        iwt_lines, remaining_product_dict = self.create_iwt_lines(channel, remaining_product_dict)
        if iwt_lines:
            ict_iwt_domain = self.ict_iwt_search_domain(warehouse_id, channel, place='iwt')
            iwt = ict_iwt_obj.search(ict_iwt_domain)
            if iwt:
                iwt = iwt[0]
                iwt.write({'intercompany_transfer_line_ids': iwt_lines})
            else:
                iwt_vals = channel.prepare_interwarehouse_values(warehouse_id, channel, data={})
                iwt_vals.update({'intercompany_transfer_line_ids': iwt_lines})
                iwt = self.env['setu.intercompany.transfer'].create(iwt_vals)
            iwt.intercompany_transfer_line_ids.product_id_change()
            iwt.onchange_requestor_warehouse_id()
            iwt.onchange_fulfiller_warehouse_id()
            if channel.location_id:
                iwt.location_id = channel.location_id.id
            if iwt.state == 'draft' and channel.validate_ict:
                iwt.action_validate_internal_transfer()
        return remaining_product_dict

    def get_product_stock(self, product_id, warehouse_id):
        wh_available = product_id.with_context({'warehouse': warehouse_id.id}).qty_available
        wh_outgoing = product_id.with_context({'warehouse': warehouse_id.id}).outgoing_qty
        net_on_hand = wh_available - wh_outgoing
        return wh_available, wh_outgoing, net_on_hand

    def get_warehouse_wise_procurement(self, procurements):
        """
        This method will create warehouse wise procurement dictionary and
        create activity if Inter Company Channel not found.
        :param procurements: Procurements.
        :return: It will return warehouse wise procurement dictionary.
        """
        procurement_dict = {}
        channel_env = self.env['setu.intercompany.channel']
        ware_channel_env = self.env['setu.interwarehouse.channel']
        for record in procurements:
            warehouse = record.values.get('warehouse_id', False)
            orderpoint = record.values and record.values.get('orderpoint_id', False) or False
            document = ""
            if orderpoint.document_creation_option == 'ict':
                channel = channel_env.get_channel_source_for_ict(warehouse.company_id.id)
                document = "ICT"
            elif orderpoint.document_creation_option == 'iwt':
                channel = ware_channel_env.get_channel_source_for_internal_transfer(warehouse.id, all_channel=True)
                document = "IWT"
            if not channel and orderpoint:
                msg = "<b>" + _("Can't create %s for this orderpoint, because %s channel not found for this company. "
                                "Create %s manually." % (document, document, document)) + "</b>"
                orderpoint.create_schedule_activity({'note': msg})
                continue
            if warehouse and warehouse.id in procurement_dict:
                existing_list = procurement_dict.get(warehouse.id)
                existing_list.append(record)
                procurement_dict.update({warehouse.id: existing_list})
            if warehouse and warehouse.id not in procurement_dict:
                procurement_dict.update({warehouse.id: [record]})
        return procurement_dict

    def prepare_ict_iwt_line_vals(self, line):
        """
        This method will prepare ICT line dictionary.
        :param line: Procurement line.
        :return: It will return dictionary.
        """
        return {
            'product_id': line.product_id.id,
            'quantity': line.product_qty,
            'unit_price': 0,
        }

    def create_ict_iwt_lines(self, warehouse_id, channel, procurements, place='ict'):
        """
        This method will create ICT line vals or update ICT lines if it is already in Draft ICT.
        :param warehouse_id: Warehouse Object.
        :param channel: Channel Object.
        :param procurements: Procurements.
        :return: It will return list of tuple of line values.
        eg. [(0, 0, {'product_id': 1, 'quantity': 10, 'unit_price': 0})]
        """
        ict_iwt_lines = []
        # line_obj = self.env['setu.intercompany.transfer.line']
        ict_obj = self.env['setu.intercompany.transfer']
        for line in procurements:
            # line_domain = self.ict_iwt_line_search_domain(line, warehouse_id, channel, place)
            ict_iwt_domain = self.ict_iwt_search_domain(warehouse_id, channel, place=place)
            existing_ict_iwt = ict_obj.search(ict_iwt_domain)
            ict_iwt_line_exists = existing_ict_iwt.intercompany_transfer_line_ids.filtered(
                lambda x: x.product_id == line.product_id)  # line_obj.search(line_domain, limit=1)
            if ict_iwt_line_exists:
                ict_iwt_line_exists[0].write({'quantity': line.product_qty})
                continue
            line_vals = self.prepare_ict_iwt_line_vals(line)
            ict_iwt_lines.append((0, 0, line_vals))
        return ict_iwt_lines

    def create_iwt_lines(self, channel, procurements, place='iwt'):
        """
        This method will create IWT line vals or update IWT lines if it is already in Draft IWT.
        :param warehouse_id: Warehouse Object.
        :param channel: Channel Object.
        :param procurements: Procurements.
        :return: It will return list of tuple of line values.
        eg. [(0, 0, {'product_id': 1, 'quantity': 10, 'unit_price': 0})]
        """
        ict_iwt_lines = []
        warehouse = channel.requestor_warehouse_id
        fulfiller_warehouse = channel.fulfiller_warehouse_id
        # line_obj = self.env['setu.intercompany.transfer.line']
        iwt_obj = self.env['setu.intercompany.transfer']
        remaining_dict = {}
        product_dict = procurements.copy()
        for product, qty in product_dict.items():
            product_obj = self.env['product.product'].browse(product)
            remaining_qty = procurements.get(product, 0)
            if not remaining_qty:
                continue

            wh_available_stock = product_obj.with_context({'warehouse': fulfiller_warehouse.id}).qty_available
            wh_outgoing_stock = product_obj.with_context({'warehouse': fulfiller_warehouse.id}).outgoing_qty
            net_on_hand = wh_available_stock - wh_outgoing_stock
            if net_on_hand <= 0.0:
                net_on_hand = 0.0
            if not net_on_hand:
                continue
            order_qty = remaining_qty
            if net_on_hand < remaining_qty:
                order_qty = net_on_hand
                procurements.update({product_obj.id: remaining_qty - order_qty if net_on_hand < remaining_qty else 0})
            else:
                procurements.pop(product_obj.id)

            # line_domain = self.ict_iwt_line_search_domain(line, warehouse_id, channel, place)
            iwt_domain = self.iwt_search_domain(warehouse, channel)
            existing_ict_iwt = iwt_obj.search(iwt_domain)
            ict_iwt_line_exists = existing_ict_iwt.intercompany_transfer_line_ids.filtered(
                lambda x: x.product_id == product_obj)  # line_obj.search(line_domain, limit=1)
            if ict_iwt_line_exists:
                ict_iwt_line_exists[0].write({'quantity': order_qty})
                # continue
            else:
                # line_vals = self.prepare_ict_iwt_line_vals(line)
                ict_iwt_lines.append((0, 0, {'product_id': product, 'quantity': order_qty, 'unit_price': 0}))

            # remaining_dict.update()
        return ict_iwt_lines, procurements

    def ict_iwt_line_search_domain(self, line, warehouse_id, channel, place='ict'):
        """
        This method will prepare a domain to check whether the product is already in any draft ICT or not.
        :param line: Procurement Line.
        :param warehouse_id: Warehouse object.
        :param channel: Channel Object.
        :return: It will return domain.
        """
        identity = 'inter_company' if place == 'ict' else 'inter_warehouse'
        channel_field = 'intercompany_channel_id' if place == 'ict' else 'interwarehouse_channel_id'
        return [('intercompany_transfer_id.%s' % channel_field, '=', channel.id),
                ('intercompany_transfer_id.requestor_warehouse_id', '=', warehouse_id.id),
                ('intercompany_transfer_id.requestor_company_id', '=', warehouse_id.company_id.id),
                ('intercompany_transfer_id.state', '=', 'draft'),
                ('intercompany_transfer_id.transfer_type', '=', identity),
                ('product_id', '=', line.product_id.id)]

    def ict_iwt_search_domain(self, warehouse_id, channel, place='ict'):
        """
        This method will prepare a domain to check whether any ICT with same warehouse and channel
        is already exists in Draft or not.
        :param warehouse_id: Warehouse object.
        :param channel: Channel Object.
        :return: It will return domain.
        """
        identity = 'inter_company' if place == 'ict' else 'inter_warehouse'
        channel_field = 'intercompany_channel_id' if place == 'ict' else 'interwarehouse_channel_id'
        return [('%s' % channel_field, '=', channel.id),
                ('requestor_warehouse_id', '=', warehouse_id.id),
                ('requestor_company_id', '=', warehouse_id.company_id.id),
                ('state', '=', 'draft'),
                ('transfer_type', '=', identity)]

    def iwt_search_domain(self, warehouse_id, channel):
        """
        This method will prepare a domain to check whether any IWT with same warehouse and channel
        is already exists in Draft or not.
        :param warehouse_id: Warehouse object.
        :param channel: Channel Object.
        :return: It will return domain.
        """
        return [('interwarehouse_channel_id', '=', channel.id),
                ('requestor_warehouse_id', '=', warehouse_id.id),
                ('requestor_company_id', '=', warehouse_id.company_id.id),
                ('state', '=', 'draft'),
                ('transfer_type', '=', 'inter_warehouse')]
