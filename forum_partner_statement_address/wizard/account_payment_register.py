# Copyright 2026 Primate (https://primate.uy)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""Atribuye el pago a la direccion de la factura que cancela.

`account.payment` hereda por delegacion de `account.move`
(`_inherits = {"account.move": "move_id"}`), asi que alcanza con agregar las
claves a los vals del pago: se escriben en el asiento.

Solo se atribuye cuando todas las lineas del lote comparten la misma
direccion. Un pago que cancela facturas de sucursales distintas se deja sin
atribuir a proposito: la parte conciliada ya sigue a cada factura, y el
remanente a cuenta no pertenece a ninguna sucursal en particular.
"""

from odoo import models


class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    def _forum_address_from_lines(self, lines):
        """Devuelve (direccion_facturacion, direccion_entrega) o (False, False)."""
        moves = lines.move_id
        if not moves:
            return False, False
        billing = moves.mapped("partner_id")
        shipping = moves.mapped("partner_shipping_id")
        return (
            billing[0].id if len(billing) == 1 else False,
            shipping[0].id if len(shipping) == 1 else False,
        )

    def _forum_apply_address(self, vals, batch_result):
        billing, shipping = self._forum_address_from_lines(
            batch_result.get("lines", self.env["account.move.line"])
        )
        vals["forum_address_partner_id"] = billing
        vals["forum_shipping_partner_id"] = shipping
        return vals

    def _create_payment_vals_from_wizard(self, batch_result):
        vals = super()._create_payment_vals_from_wizard(batch_result)
        return self._forum_apply_address(vals, batch_result)

    def _create_payment_vals_from_batch(self, batch_result):
        vals = super()._create_payment_vals_from_batch(batch_result)
        return self._forum_apply_address(vals, batch_result)
