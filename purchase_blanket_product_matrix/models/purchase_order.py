# -*- coding: utf-8 -*-
from odoo import api, models, _
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def button_confirm(self):
        for order in self:
            req = order.requisition_id  # blanket link
            if req:
                # Map allowed qty per product on requisition lines
                allowed = {}
                for l in req.line_ids:
                    allowed[l.product_id.id] = allowed.get(l.product_id.id, 0.0) + (l.product_qty or 0.0)

                # Already confirmed qty across other POs of this requisition
                confirmed_orders = self.search([
                    ("requisition_id", "=", req.id),
                    ("state", "in", ["purchase", "done"]),
                    ("id", "!=", order.id),
                ])
                used = {}
                for po in confirmed_orders:
                    for line in po.order_line:
                        pid = line.product_id.id
                        used[pid] = used.get(pid, 0.0) + (line.product_qty or 0.0)

                # Current order qty
                current = {}
                for line in order.order_line:
                    pid = line.product_id.id
                    current[pid] = current.get(pid, 0.0) + (line.product_qty or 0.0)

                # Validate
                errors = []
                for pid, qty in current.items():
                    max_qty = allowed.get(pid, 0.0)
                    if max_qty <= 0:
                        # If not in blanket, skip (blanket may have generic lines; keep strict? we skip)
                        continue
                    new_total = used.get(pid, 0.0) + qty
                    if new_total > max_qty + 1e-9:
                        product = self.env["product.product"].browse(pid)
                        errors.append(_("- %s: permitido %.2f / ya confirmado %.2f / intentando confirmar %.2f (total %.2f)") % (
                            product.display_name, max_qty, used.get(pid, 0.0), qty, new_total
                        ))
                if errors:
                    raise UserError(_("El pedido excede las cantidades acordadas en el Acuerdo de compra:\n%s") % ("\n".join(errors)))

        return super().button_confirm()
