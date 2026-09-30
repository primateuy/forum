# -*- coding: utf-8 -*-
"""
Campos de agrupación para la consulta de pagos del punto de venta.

El modelo pos.payment ya trae la sesión y la compañía almacenadas, pero no el
punto de venta ni el cajero, que son los dos cortes que más se usan al revisar
la venta diaria. Se agregan como campos relacionados almacenados porque el ORM
no permite agrupar ni filtrar por campos sin almacenar.
"""

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class PosPayment(models.Model):
    """
    Agrega a los pagos del POS el punto de venta y el cajero de la orden.

    Ambos salen de pos.order, que ya los tiene resueltos: config_id es a su vez
    un relacionado almacenado de la sesión, y user_id es el usuario que cerró
    la venta.
    """

    _inherit = 'pos.payment'

    config_id = fields.Many2one(
        comodel_name='pos.config',
        string='Punto de venta',
        related='pos_order_id.config_id',
        store=True,
        index=True,
        # index=True: es el campo de la regla de registro que recorta por local,
        # así que entra en el WHERE de toda consulta al modelo.
        ondelete='restrict',
        help='Punto de venta donde se registró el pago.',
    )
    user_id = fields.Many2one(
        comodel_name='res.users',
        string='Cajero',
        related='pos_order_id.user_id',
        store=True,
        ondelete='restrict',
        help='Usuario que registró la venta en el punto de venta.',
    )

    # ------------------------------------------------------------------
    # Datos de la tarjeta, tomados de la transacción del adquirente
    #
    # El campo card_type del núcleo no sirve para esto: en FORUM llega vacío
    # en casi todos los pagos y, cuando trae algo, es el código numérico del
    # adquirente (1, 8), no la marca. Los datos de la tarjeta los guarda la
    # integración de la terminal en payment.transaction.
    # ------------------------------------------------------------------

    issuer_name = fields.Char(
        string='Sello',
        related='payment_transaction_id.issuer_name',
        store=True,
        index=True,
        help='Marca de la tarjeta informada por la terminal: Visa, Visa Débito, '
             'Mastercard. Vacío en los pagos que no pasan por terminal.',
    )
    card_last_four = fields.Char(
        string='Últimos 4',
        related='payment_transaction_id.card_last_four',
        store=False,
        help='Últimos cuatro dígitos de la tarjeta.',
    )
