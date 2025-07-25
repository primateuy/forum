# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model
    def _order_fields(self, ui_order):
        session = self.env['pos.session'].browse(ui_order.get('pos_session_id'))
        user_id = False
        if session and session.user_id:
            user_id = session.user_id.id
        ui_order['user_id'] = user_id
        return super(PosOrder, self)._order_fields(ui_order)

    def _get_fields_for_order_line(self):
        fields = super(PosOrder, self)._get_fields_for_order_line()
        fields.extend([
            'user_id',
        ])
        return fields


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    user_id = fields.Many2one('res.users', string='Salesperson')

    def _export_for_ui(self, orderline):
        result = super(PosOrderLine, self)._export_for_ui(orderline)
        result['user_id'] = orderline.user_id.id
        return result
