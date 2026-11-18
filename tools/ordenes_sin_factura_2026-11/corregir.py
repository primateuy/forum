# -*- coding: utf-8 -*-
"""
Correcciones de datos de las órdenes del PDV registradas sin factura (casos B, D y E).

Relevado en producción, sólo lectura, el 18-11-2026. Ver la KB de forum
(«Estado actual» del 18-11 y el informe Forum_Ordenes_Sin_Factura_2026-11-18.pdf).

🔴 NADA de esto se corre sin la orden explícita de Daryl, caso por caso. D y E,
además, después de que contabilidad (Diego) defina el asiento de ajuste.

Uso, dentro de ``odoo-bin shell`` sobre la base:

    exec(open('<ruta>/corregir.py').read())
    corregir('B')                  # en seco: muestra qué cambiaría y deshace
    corregir('B', aplicar=True)    # escribe y confirma

Antes de escribir guarda un CSV con los valores anteriores en el directorio de
este archivo. Si un registro no está como se leyó el 18-11 (alguien lo tocó),
aborta sin escribir nada.
"""
import csv
import datetime
import os

DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else '.'


class Distinto(Exception):
    """Un registro no está como se relevó: no se toca nada."""


def _esperar(registro, campo, esperado):
    actual = registro[campo]
    if hasattr(actual, 'id'):
        actual = actual.id or False
    if isinstance(esperado, float) or isinstance(actual, float):
        if abs(float(actual or 0) - float(esperado or 0)) > 0.001:
            raise Distinto(f'{registro} {campo}: se esperaba {esperado}, está {actual}')
    elif actual != esperado:
        raise Distinto(f'{registro} {campo}: se esperaba {esperado!r}, está {actual!r}')


def _respaldo(caso, filas):
    nombre = os.path.join(DIR, f'respaldo_{caso}_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv')
    with open(nombre, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['modelo', 'id', 'campo', 'valor_anterior', 'valor_nuevo'])
        w.writerows(filas)
    print('respaldo:', nombre)


# ---------------------------------------------------------------------------
# B: la transacción OCA apunta a una orden de OTRA caja (el pago sí es el correcto).
#    No impide facturar; deja limpia la conciliación con OCA y el voucher.
# ---------------------------------------------------------------------------
B_TX = [
    # tx, orden equivocada (otra caja), orden correcta (la de su pago)
    (12875, 19745, 19755),  # Orden 01336-001-0018, Pando
    (13311, 20383, 20385),  # Orden 01422-001-0004, Pando
    (15477, 23271, 23275),  # Orden 01501-007-0002, Pando
]


def _caso_b(env):
    Tx = env['payment.transaction'].sudo()
    filas = []
    for tx_id, mala, buena in B_TX:
        tx = Tx.browse(tx_id)
        _esperar(tx, 'pos_order_id', mala)
        if tx.pos_payment_id.pos_order_id.id != buena:
            raise Distinto(f'tx {tx_id}: su pago es de la orden {tx.pos_payment_id.pos_order_id.id}, no {buena}')
        filas.append(['payment.transaction', tx_id, 'pos_order_id', mala, buena])
        tx.pos_order_id = buena
    return filas


# ---------------------------------------------------------------------------
# D: Orden 03192-001-0017 (56509), Atlántico. Quedó con la tx 39688 de la venta
#    anterior (registrada por respaldo, aut. 227244); la suya es la 39694 (3.980).
#    🔴 Antes: asiento de ajuste de contabilidad (la caja cerró con 2.864).
# ---------------------------------------------------------------------------
def _caso_d(env):
    Pago = env['pos.payment'].sudo()
    Tx = env['payment.transaction'].sudo()
    orden = env['pos.order'].sudo().browse(56509)
    pago = Pago.browse(63371)
    vieja, propia = Tx.browse(39688), Tx.browse(39694)
    _esperar(orden, 'state', 'done')
    _esperar(orden, 'account_move', False)
    _esperar(pago, 'pos_order_id', 56509)
    _esperar(pago, 'amount', 2864.0)
    _esperar(pago, 'transaction_id', '2631952912169939')
    _esperar(pago, 'payment_transaction_id', 39688)
    _esperar(vieja, 'pos_order_id', 56509)
    _esperar(vieja, 'pos_payment_id', 63371)
    _esperar(propia, 'pos_order_id', False)
    _esperar(propia, 'pos_payment_id', False)
    _esperar(propia, 'amount', 3980.0)
    _esperar(propia, 'oca_transaction_id', '2631953472150525')
    descuento = orden.lines.filtered(lambda l: l.price_unit < 0)
    if len(descuento) != 1:
        raise Distinto(f'orden 56509: {len(descuento)} líneas de descuento')
    _esperar(descuento, 'price_unit', -716.0)

    filas = [
        ['payment.transaction', 39688, 'pos_order_id/pos_payment_id', '56509/63371', 'False/False'],
        ['pos.payment', 63371, 'amount', 2864.0, 3980.0],
        ['pos.payment', 63371, 'transaction_id', '2631952912169939', '2631953472150525'],
        ['pos.payment', 63371, 'payment_transaction_id', 39688, 39694],
        ['payment.transaction', 39694, 'pos_order_id/pos_payment_id', 'False/False', '56509/63371'],
        ['pos.order.line', descuento.id, 'price_unit', -716.0, -995.0],
    ]
    vieja.write({'pos_order_id': False, 'pos_payment_id': False})
    pago.write({'amount': 3980.0, 'transaction_id': '2631953472150525', 'payment_transaction_id': 39694})
    propia.write({'pos_order_id': 56509, 'pos_payment_id': 63371, 'invoice_number': orden.name})
    # 20 % sobre lo comprado: 4.975 × 0,20 = 995.
    descuento.write({'price_unit': -995.0})
    # En v17 los subtotales de la línea se guardan, no se recalculan solos.
    descuento.write(descuento._compute_amount_line_all())
    orden._compute_batch_amount_all()
    if abs(orden.amount_total - orden.amount_paid) > 0.001 or abs(orden.amount_total - 3980.0) > 0.001:
        raise Distinto(f'orden 56509 quedó en total {orden.amount_total} / pagado {orden.amount_paid}')
    return filas


# ---------------------------------------------------------------------------
# E: Orden 01418-004-0002 (20475), Minas: copia de la 20472 (ya facturada). Se
#    cancela para que salga de las pendientes. No movió stock (sin picking).
#    🔴 Antes: contabilidad revierte su efecto en el cierre de la sesión 1418
#    (diferencia de caja +2.784 de más, 2.227,19 de tarjeta de más, 556,81 de
#    «Ajuste por redondeo»).
# ---------------------------------------------------------------------------
def _caso_e(env):
    orden = env['pos.order'].sudo().browse(20475)
    original = env['pos.order'].sudo().browse(20472)
    _esperar(orden, 'state', 'done')
    _esperar(orden, 'account_move', False)
    _esperar(orden, 'pos_reference', 'Orden 01418-004-0002')
    _esperar(original, 'pos_reference', 'Orden 01418-004-0002')
    _esperar(original, 'state', 'invoiced')
    if orden.picking_ids:
        raise Distinto('la copia tiene picking: revisar antes')
    nota = ('Duplicado de %s (misma referencia, guardada 22 s después). Cancelada el %s; '
            'el efecto en el cierre de la sesión 1418 lo ajusta contabilidad.') % (
        original.name, datetime.date.today())
    filas = [['pos.order', 20475, 'state', 'done', 'cancel'],
             ['pos.order', 20475, 'note', orden.note or '', nota]]
    orden.write({'state': 'cancel', 'note': ((orden.note or '') + '\n' + nota).strip()})
    return filas


CASOS = {'B': _caso_b, 'D': _caso_d, 'E': _caso_e}


def corregir(caso, aplicar=False):
    filas = CASOS[caso](env)  # noqa: F821 — env lo da odoo-bin shell
    for f in filas:
        print(' ', *f)
    if not aplicar:
        env.cr.rollback()  # noqa: F821
        print(f'caso {caso}: EN SECO, nada escrito ({len(filas)} cambios previstos)')
        return
    _respaldo(caso, filas)
    env.cr.commit()  # noqa: F821
    print(f'caso {caso}: APLICADO ({len(filas)} cambios)')
