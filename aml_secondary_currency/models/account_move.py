# -*- coding: utf-8 -*-
from odoo import models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        res = super()._post(soft=soft)
        # Recalcular SOLO sobre los asientos que efectivamente quedaron posteados.
        # Con `soft=True` (default), el core saltea los asientos cuya `date > today`
        # y los deja en borrador; aplicar `compute_amount_secondary` sobre esos
        # rompe con "No se encontró tipo de cambio" porque la fecha futura no tiene
        # rate cargado todavía. Esto pasaba al confirmar activos con amortizaciones
        # futuras y al devengamiento de gastos, que generan asientos borrador con
        # fechas futuras. Cuando llegue su fecha y se posteen, esta función volverá
        # a correr y recalculará el importe en divisa secundaria con el rate real.
        posted = self.filtered(lambda m: m.state == 'posted')
        if posted:
            posted.line_ids.compute_amount_secondary()
        return res