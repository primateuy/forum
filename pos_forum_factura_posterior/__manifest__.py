# -*- coding: utf-8 -*-
{
    "name": "PDV Forum — Facturar una venta después del cierre",
    "version": "17.0.1.0.0",
    "summary": "Permite emitir la factura de una venta del PDV cuando el cliente la pide después, con la fecha de la venta.",
    "description": """
Facturar una venta del PDV después del cierre de caja
=====================================================

El core ya sabe hacerlo: ``action_pos_order_invoice`` crea la factura y, si la
sesión está cerrada, revierte la parte de esa venta dentro del asiento de cierre
(``_create_misc_reversal_move``) para no contabilizarla dos veces.

Lo que faltaba:

* **El botón no se veía.** En el formulario de la orden está condicionado a
  ``state == 'paid'``, y al cerrar la caja las ventas no facturadas pasan a
  ``done``. Este módulo agrega el botón para ese estado, restringido a
  responsables de PDV y facturación.
* **Las fechas quedaban en "hoy".** El core fuerza ``invoice_date = now()``
  cuando la sesión está cerrada, y fecha la reversión del cierre también hoy.
  Acá las dos toman la fecha real de la venta: para UCFE lo que vale es la fecha
  de firma, y así la factura y la reversión quedan en el mismo período que el
  asiento de cierre que corrigen —y que los asientos de pago, que el core ya
  fecha con ``date_order``—.

El botón del PDV sigue oculto (``odoo_pos_no_invoice``): esto es sólo backend.
    """,
    "author": "PRIMATE",
    "category": "Point of Sale",
    "license": "LGPL-3",
    # pos_invoice_auto_check es el que crea y postea la factura del PDV; va en
    # depends para quedar después en el MRO, igual que pos_forum_cfe_pendiente.
    "depends": ["point_of_sale", "account", "pos_invoice_auto_check"],
    "data": [
        "data/server_action.xml",
        "views/pos_order_views.xml",
    ],
    "installable": True,
    "application": False,
}
