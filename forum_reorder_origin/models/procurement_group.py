# -*- coding: utf-8 -*-
from odoo import api, models
from odoo.addons.stock.models.stock_rule import ProcurementException


class ProcurementGroup(models.Model):
    _inherit = 'procurement.group'

    @api.model
    def run(self, procurements, raise_user_error=True):
        """Junta los errores del reabastecimiento tolerante para avisarlos al final.

        El core los aparta y sigue con el resto, pero sólo los deja como actividad en la
        ficha del producto: quien ordenó desde la pantalla no se enteraría de qué quedó
        afuera. Se re-lanza siempre: el core necesita la excepción para apartar las reglas.
        """
        try:
            return super().run(procurements, raise_user_error=raise_user_error)
        except ProcurementException as e:
            if self.env.context.get('reposicion_tolerante'):
                errores = self.env.cr.cache.setdefault('forum_reposicion_errores', [])
                Orderpoint = self.env['stock.warehouse.orderpoint']
                for procurement, mensaje in e.procurement_exceptions:
                    orderpoint = procurement.values.get('orderpoint_id') or Orderpoint
                    errores.append((orderpoint, mensaje))
            raise
