# -*- coding: utf-8 -*-
"""Corrige la «Demanda a considerar» que quedó desfasada de la cantidad a pedir.

Hasta esta versión, cuando el core recalculaba `qty_to_order` con `env.add_to_compute()`
(al cambiar los movimientos de stock y al ordenar), `forum_demand_effective` no se
recalculaba. Las reglas desfasadas en 0 no entraban al cálculo de no cumplibles y el filtro
«Reglas cumplibles» las mostraba aunque el origen no tuviera stock.

Misma fórmula que `_compute_forum_demand_effective`. Por SQL porque son ~600 mil reglas y
el campo depende sólo de dos columnas del propio registro; sólo se tocan las desfasadas.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE stock_warehouse_orderpoint
           SET forum_demand_effective = CASE WHEN COALESCE(forum_demand_original, 0) > 0
                                             THEN forum_demand_original
                                             ELSE COALESCE(qty_to_order, 0) END
         WHERE COALESCE(forum_demand_effective, 0) IS DISTINCT FROM
               CASE WHEN COALESCE(forum_demand_original, 0) > 0
                    THEN forum_demand_original
                    ELSE COALESCE(qty_to_order, 0) END
    """)
    _logger.info("forum_reorder_origin: demanda a considerar corregida en %s regla(s)",
                 cr.rowcount)
