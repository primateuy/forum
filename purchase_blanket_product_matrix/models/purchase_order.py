# -*- coding: utf-8 -*-
from odoo import api, models, _
from odoo.exceptions import UserError

class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def button_confirm(self):
        # Validación de cantidades vs Acuerdo de compra (Orden abierta / Blanket)
        for order in self:
            if not order.requisition_id or order.requisition_id.type != "blanket_order":
                continue

            # Solo validar líneas que vienen del acuerdo (link a requisition line)
            if "requisition_line_id" not in self.env["purchase.order.line"]._fields:
                continue

            # Agrupar por línea del acuerdo
            lines_by_req_line = {}
            for line in order.order_line.filtered(lambda l: l.requisition_line_id):
                lines_by_req_line.setdefault(line.requisition_line_id, self.env["purchase.order.line"])
                lines_by_req_line[line.requisition_line_id] |= line

            for req_line, lines in lines_by_req_line.items():
                agreement_qty = req_line.product_qty or 0.0
                agreement_uom = req_line.product_uom_id

                # Cantidad de ESTE pedido (convertida a UoM del acuerdo)
                current_qty = 0.0
                for l in lines:
                    qty = l.product_qty or 0.0
                    if l.product_uom and agreement_uom and l.product_uom != agreement_uom:
                        qty = l.product_uom._compute_quantity(qty, agreement_uom)
                    current_qty += qty

                # Cantidad ya comprometida en otros pedidos confirmados (purchase/done)
                other_lines = self.env["purchase.order.line"].search([
                    ("requisition_line_id", "=", req_line.id),
                    ("order_id", "!=", order.id),
                    ("order_id.state", "in", ("purchase", "done")),
                ])

                other_qty = 0.0
                for ol in other_lines:
                    qty = ol.product_qty or 0.0
                    if ol.product_uom and agreement_uom and ol.product_uom != agreement_uom:
                        qty = ol.product_uom._compute_quantity(qty, agreement_uom)
                    other_qty += qty

                total_qty = other_qty + current_qty
                # tolerancia mínima flotante
                if total_qty > agreement_qty + 1e-6:
                    raise UserError(_(
                        "No se puede confirmar el pedido porque excede la cantidad acordada en la Orden de compra abierta.\n\n"
                        "Producto: %(product)s\n"
                        "Cantidad acordada: %(ag)s %(uom)s\n"
                        "Ya confirmada en otros pedidos: %(other)s %(uom)s\n"
                        "Este pedido intenta confirmar: %(cur)s %(uom)s\n"
                        "Total confirmado quedaría en: %(tot)s %(uom)s\n"
                    ) % {
                        "product": req_line.product_id.display_name,
                        "ag": agreement_qty,
                        "other": other_qty,
                        "cur": current_qty,
                        "tot": total_qty,
                        "uom": agreement_uom.display_name if agreement_uom else "",
                    })

        return super().button_confirm()
