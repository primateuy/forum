# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    user_id = fields.Many2one('hr.employee', string='Salesperson')

    def _export_for_ui(self, orderline):
        result = super(PosOrderLine, self)._export_for_ui(orderline)
        result['user_id'] = orderline.user_id.id
        print('RE:::::::::::::::::', result)
        return result


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _get_fields_for_order_line(self):
        fields = super(PosOrder, self)._get_fields_for_order_line()
        fields.extend([
            'user_id',
        ])
        return fields
