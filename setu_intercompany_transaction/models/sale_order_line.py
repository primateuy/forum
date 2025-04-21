from odoo import models, fields, api, _


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.model
    def default_get(self, fields_list):
        res = super(SaleOrderLine, self).default_get(fields_list)
        order = self.order_id.browse(self._context.get('order_id')) if self._context.get('order_id') else False
        res[
            'interwarehouse_channel_id'] = order.interwarehouse_channel_id.id if order and order.interwarehouse_channel_id else False
        return res

    interwarehouse_channel_id = fields.Many2one("setu.interwarehouse.channel", "Interwarehouse Channel", copy=False,
                                                index=True,
                                                domain="[('requestor_warehouse_id','=',parent.warehouse_id)]")
