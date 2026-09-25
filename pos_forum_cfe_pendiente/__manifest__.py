# -*- coding: utf-8 -*-
{
    "name": "PDV Forum — Emisión de CFE pendiente",
    "version": "17.0.1.0.0",
    "summary": "Si la emisión del CFE falla, la venta no se pierde: queda con la factura en borrador y el PDV permite reintentar sólo la emisión.",
    "description": """
Emisión de CFE pendiente en el PDV
==================================

Hasta ahora, validar una venta en el PDV hacía todo en una sola transacción:
crear la orden, crear la factura y emitir el CFE. Si la emisión fallaba —un
receptor sin configurar, Uruware caído, un dato fiscal faltante— **revertía
todo** y la venta no quedaba en ningún lado, aunque el cobro ya se hubiera hecho.

Con este módulo:

* la venta y la factura quedan creadas; la factura queda en **borrador**,
* el PDV muestra el error y **no deja avanzar ni volver atrás**: la única salida
  es reintentar la emisión de esa misma factura,
* el cierre de caja queda **bloqueado** mientras haya emisiones pendientes.

Es el mismo criterio que ya aplica ``l10n_uy_cfc_efac`` para los comprobantes de
contingencia: la confirmación en Odoo y el envío a UCFE son responsabilidades
separadas.
    """,
    "author": "PRIMATE",
    "category": "Point of Sale",
    "license": "LGPL-3",
    # pos_invoice_auto_check es el que crea y postea la factura del PDV: hace
    # falta en depends para que el override caiga DESPUÉS en el MRO.
    "depends": ["point_of_sale", "pos_invoice_auto_check"],
    "data": [
        "views/pos_order_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_forum_cfe_pendiente/static/src/js/cfe_pendiente.js",
            "pos_forum_cfe_pendiente/static/src/xml/cfe_pendiente_screen.xml",
        ],
    },
    "installable": True,
    "application": False,
}
