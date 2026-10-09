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
        """Sincroniza el múltiplo de distribución a las reglas de reabastecimiento.

        Sólo escribe las reglas cuyo múltiplo cambia, y difiere el recálculo de la cantidad
        a pedir (`reorden_rendimiento`): con una plantilla de 1.500 variantes son ≈ 60.000
        reglas, y recalcularlas dentro del guardado pasaba el límite de tiempo.
        """
        Recalculo = self.env['reorden.recalculo.pendiente']
        for template in self:
            multiple = float(template.mutiplos_distribucion or 1)
            orderpoints = self.env['stock.warehouse.orderpoint'].search([
                ('product_id.product_tmpl_id', '=', template.id),
                ('qty_multiple', '!=', multiple),
            ])
            if orderpoints:
                with Recalculo.diferir(plantillas=template, origen="Cambio de múltiplo"):
                    orderpoints.with_context(tracking_disable=True).write({'qty_multiple': multiple})
