# Copyright 2026 Primate (https://primate.uy)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""Direccion a la que se atribuye un pago, para el estado de cuenta.

Decision de diseno: NO se toca `account.payment.partner_id` ni el partner de
los apuntes. En Odoo 17 las lineas del pago copian `self.partner_id` tal cual
(`account/models/account_payment.py`, lineas 345 y 356), asi que cambiarlo
moveria datos contables a la sucursal y dejaria al reporte OCA nativo del
partner padre sin ver esos pagos, ademas de meterse con la conciliacion.

En lugar de eso se guardan dos campos espejo, solo informativos, que el
wizard de registro de pago completa con la direccion de la factura que se
esta cancelando. El agrupamiento del reporte los lee; la contabilidad no se
entera de que existen.

Los pagos anteriores a este modulo quedan con los campos vacios y caen en el
apartado del partner comercial ("nivel empresa"), que es justamente la regla
acordada para los pagos a cuenta sin direccion.
"""

from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    forum_address_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Direccion de facturacion atribuida",
        ondelete="set null",
        index=True,
        copy=False,
        help="Solo para pagos: direccion de facturacion de la factura que "
        "cancela. La usa el estado de cuenta agrupado por direccion. No "
        "tiene ningun efecto contable.",
    )
    forum_shipping_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Direccion de entrega atribuida",
        ondelete="set null",
        index=True,
        copy=False,
        help="Solo para pagos: direccion de entrega de la factura que "
        "cancela. La usa el estado de cuenta agrupado por direccion. No "
        "tiene ningun efecto contable.",
    )
