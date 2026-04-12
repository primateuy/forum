from odoo import models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_autoinvoice_by_limit(self):
        """Acción de servidor que abre el wizard de facturación por límite de líneas."""
        return {
            "type": "ir.actions.act_window",
            "name": "Facturar por límite de líneas",
            "res_model": "sale.autoinvoice.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "active_ids": self.ids,
                "active_model": "sale.order",
            },
        }
