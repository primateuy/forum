# -*- coding: utf-8 -*-

from odoo import api, models


class AccountMove(models.Model):
    """Asiento contable, con la fecha que le pide la reversión del cierre del PDV."""

    _inherit = "account.move"

    @api.model_create_multi
    def create(self, vals_list):
        """
        Aplica la fecha marcada para la reversión del asiento de cierre.

        Existe porque el core escribe esa fecha dentro del ``create`` y no la
        deja pasar por parámetro (point_of_sale/models/pos_order.py:858). El
        contexto ``forum_fecha_reversion`` lo pone
        ``pos.order._create_misc_reversal_move`` y vive sólo durante esa
        llamada, donde el único asiento que se crea es el de reversión: no
        alcanza a ningún otro ``account.move``.
        """
        fecha = self.env.context.get("forum_fecha_reversion")
        if fecha:
            for vals in vals_list:
                vals["date"] = fecha
        return super().create(vals_list)
