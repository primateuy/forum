# -*- coding: utf-8 -*-

from odoo import api, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.onchange('requisition_id')
    def _onchange_requisition_id(self):
        super()._onchange_requisition_id()

        requisition = self.requisition_id
        if not requisition or not requisition.type_id.use_remaining_qty:
            return
        if requisition.type_id.quantity_copy != 'copy':
            return
        if requisition.type_id.line_copy != 'copy':
            return

        # Cantidades ya asignadas por producto en POs de este contrato (excepto canceladas)
        qty_ordered_map = {}
        for po in requisition.purchase_ids.filtered(lambda p: p.state != 'cancel'):
            if po == self._origin:
                continue
            for po_line in po.order_line:
                key = (
                    po_line.product_id.id,
                    tuple(sorted(po_line.product_no_variant_attribute_value_ids.ids)),
                )
                qty_ordered_map[key] = qty_ordered_map.get(key, 0.0) + po_line.product_qty

        if not qty_ordered_map:
            return

        # Actualizar las líneas que super() agregó buscando por producto
        for order_line in self.order_line:
            key = (
                order_line.product_id.id,
                tuple(sorted(order_line.product_no_variant_attribute_value_ids.ids)),
            )
            qty_ordered = qty_ordered_map.get(key, 0.0)
            if qty_ordered:
                order_line.product_qty = max(0.0, order_line.product_qty - qty_ordered)
