from dateutil import relativedelta
from odoo import fields, models, api, _


class AdvanceProcurementProcessConfig(models.Model):
    _name = 'advance.procurement.process.config'
    _description = "Advance Procurement Process Configuration"

    warehouse_id = fields.Many2one('stock.warehouse', string="Warehouse",
                                   help="Set Warehouse group placed reorder")
    transit_days = fields.Integer('Transit days', help="Estimated time of arrival (ETA)")
    shipment_date = fields.Date('Replenishment start', help="Set replenishment shipped date")
    shipment_arrival_date = fields.Date('Replenishment end', help="Set estimated arrival date of shipment")
    advance_stock_start_date = fields.Date('Coverage days start', help="Buffer days start date")
    advance_stock_end_date = fields.Date('Coverage days end', help="Coverage days end date")
    procurement_process_id = fields.Many2one('advance.procurement.process', string="Procurement process")
    inter_company_channel_id = fields.Many2one('setu.intercompany.channel', string="Inter company channel")
    inter_warehouse_channel_id = fields.Many2one('setu.interwarehouse.channel', string="Inter warehouse channel")
    # warehouse_ids = fields.Many2many('stock.warehouse', compute="compute_warehouse_ids", string="Warehouses")

    @api.onchange('warehouse_id')
    def onchange_warehouse_id(self):
        inter_company_channel_obj = self.env['setu.intercompany.channel']
        inter_warehouse_channel_obj = self.env['setu.interwarehouse.channel']
        procurement_warehouse_id = self.procurement_process_id.warehouse_id
        if procurement_warehouse_id and self.warehouse_id:
            fulfiller_wh_company_id = procurement_warehouse_id.sudo().company_id
            requestor_wh_company_id = self.warehouse_id.sudo().company_id
            if not fulfiller_wh_company_id == requestor_wh_company_id:
                ict_id = inter_company_channel_obj.search([('fulfiller_warehouse_id', '=', procurement_warehouse_id.id),
                                                           ('requestor_company_id', '=', requestor_wh_company_id.id)])
                if ict_id:
                    self.inter_company_channel_id = ict_id.id
                    self.transit_days = ict_id.procurement_lead_days
            elif fulfiller_wh_company_id == requestor_wh_company_id:
                iwt_id = inter_warehouse_channel_obj.search(
                    [('fulfiller_warehouse_id', '=', procurement_warehouse_id.id),
                     ('requestor_warehouse_id', '=', self.warehouse_id.id)], limit=1)
                if iwt_id:
                    self.inter_warehouse_channel_id = iwt_id.id
                    self.transit_days = iwt_id.procurement_lead_days or False
        #
        # if self._context.get('parent_warehouse_id'):
        #     parent_warehouse_id = self._context.get('parent_warehouse_id')
        #     return {'domain': {'warehouse_id': [('id', '!=', parent_warehouse_id)]}}

    @api.onchange('transit_days')
    def onchange_transit_days(self):
        self.shipment_date = self.procurement_process_id.procurement_date.date()
        days = self.transit_days - 1 if self.transit_days > 0.0 else self.transit_days
        self.shipment_arrival_date = (self.shipment_date +
                                      relativedelta.relativedelta(days=days)).strftime("%Y-%m-%d")

    @api.onchange('shipment_arrival_date')
    def onchange_shipment_arrival_date(self):
        self.advance_stock_start_date = (self.shipment_arrival_date +
                                         relativedelta.relativedelta(days=1)).strftime("%Y-%m-%d")
        days = self.procurement_process_id.buffer_stock_days - 1 \
            if self.procurement_process_id.buffer_stock_days > 0.0 \
            else self.procurement_process_id.buffer_stock_days
        self.advance_stock_end_date = (self.advance_stock_start_date +
                                       relativedelta.relativedelta(days=days)).strftime("%Y-%m-%d")
