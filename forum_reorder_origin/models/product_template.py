# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def write(self, vals):
        res = super().write(vals)
        if 'mutiplos_distribucion' in vals:
            self._sync_distribution_multiple_to_orderpoints()
        return res

    def _sync_distribution_multiple_to_orderpoints(self):
        """Sincroniza el múltiplo de distribución a las reglas de reabastecimiento."""
        for template in self:
            multiple = template.mutiplos_distribucion or 1
            orderpoints = self.env['stock.warehouse.orderpoint'].search([
                ('product_id.product_tmpl_id', '=', template.id),
            ])
            if orderpoints:
                orderpoints.write({'qty_multiple': float(multiple)})
