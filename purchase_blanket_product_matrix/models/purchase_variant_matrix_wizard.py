# -*- coding: utf-8 -*-
from odoo import api, models, _
from odoo.exceptions import UserError


class PurchaseVariantMatrixWizard(models.TransientModel):
    _inherit = "purchase.variant.matrix.wizard"

    def _pbpm_get_active(self):
        active_model = self.env.context.get("active_model")
        active_id = self.env.context.get("active_id")
        if not active_model or not active_id:
            return None, None
        return active_model, self.env[active_model].browse(active_id)

    def action_confirm(self):
        active_model, active = self._pbpm_get_active()
        if active_model == "purchase.requisition" and active:
            return self._pbpm_confirm_on_requisition(active)
        return super().action_confirm()

    def _pbpm_confirm_on_requisition(self, requisition):
        self.ensure_one()
        # purchase_product_matrix wizard usually stores matrix values in lines; we use its helper if exists.
        # Most OCA implementations provide method _get_matrix() or field matrix_line_ids.
        matrix_lines = []
        if hasattr(self, "matrix_line_ids"):
            matrix_lines = self.matrix_line_ids
        elif hasattr(self, "line_ids"):
            matrix_lines = self.line_ids

        if not matrix_lines:
            # fallback: try generic get qty mapping
            if hasattr(self, "_get_matrix_quantities"):
                qty_map = self._get_matrix_quantities()
            else:
                raise UserError(_("No pude leer los valores de la matriz. Revisá la versión de purchase_product_matrix instalada."))
        else:
            qty_map = {}
            for ml in matrix_lines:
                # Try common field names
                product = getattr(ml, "product_id", False)
                qty = getattr(ml, "qty", None)
                if qty is None:
                    qty = getattr(ml, "quantity", 0.0)
                if product and qty:
                    qty_map[product.id] = qty_map.get(product.id, 0.0) + float(qty)

        # Create / update requisition lines
        ReqLine = self.env["purchase.requisition.line"]
        for pid, qty in qty_map.items():
            if qty <= 0:
                continue
            product = self.env["product.product"].browse(pid)
            existing = requisition.line_ids.filtered(lambda l: l.product_id.id == pid)
            if existing:
                existing.product_qty += qty
            else:
                ReqLine.create({
                    "requisition_id": requisition.id,
                    "product_id": pid,
                    "product_qty": qty,
                    "product_uom_id": product.uom_id.id,
                    # price_unit: keep 0 by default so they set marco; if there is a line default, try seller? keep 0
                    "price_unit": 0.0,
                })

        return {"type": "ir.actions.act_window_close"}
