# -*- coding: utf-8 -*-
"""Las recepciones de tienda no exigen el múltiplo de distribución.

El múltiplo se controla al preparar en POLO. Al recibir en la tienda, una
preparación parcial de WIS que no es múltiplo trababa la recepción y la sucursal no
tiene el permiso de saltearlo (support, Suc. Centro, 002/POLO-IN/00002, 02-11-2026).
Decidido por Daryl: se saca «Respeta Múltiplos» de los tipos «Recepcion desde
Deposito Central».

El campo es de automatic_crossdocking (WMS), del que este módulo no depende: si no
está instalado no hay nada que hacer.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

NOMBRE = 'Recepcion desde Deposito Central'


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Tipo = env['stock.picking.type'].with_context(active_test=False)
    if 'respeta_multiplos' not in Tipo._fields:
        return
    cr.execute("""
        SELECT id FROM stock_picking_type
         WHERE code = 'incoming' AND respeta_multiplos
           AND %s IN (name->>'es_UY', name->>'en_US')
    """, [NOMBRE])
    tipos = Tipo.browse([fila[0] for fila in cr.fetchall()])
    tipos.write({'respeta_multiplos': False})
    _logger.info('Recepciones de tienda sin «Respeta Múltiplos»: %s tipos %s',
                 len(tipos), tipos.ids)
