# -*- coding: utf-8 -*-
"""Valoración en las pantallas de inventario que el perfil sí ve.

El perfil entra a Ajustes de inventario y a la Consulta de Stock. Las dos exponen
valorización, y la Consulta de Stock es además una vista **pivot**, donde las medidas
se eligen en runtime desde un desplegable armado con `fields_get`. Por eso estos campos
van con `groups=` y no con la capa de presentación.
"""
from odoo import models, fields

COST_GROUP = 'forum_branch_security.group_product_cost'


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    value = fields.Monetary(groups=COST_GROUP)
    # Los dos de tchistorico, en moneda de reportería.
    value_report = fields.Monetary(groups=COST_GROUP)
    unit_value_report = fields.Monetary(groups=COST_GROUP)


class StockQuantProductLocationReport(models.Model):
    """La Consulta de Stock.

    El perfil ve esta pantalla —puede buscar un artículo y ver su disponibilidad por
    local y por talle— pero sin costo ni margen.
    """
    _inherit = 'stock.quant.product.location.report'

    # Float, no Monetary: en la vista SQL del reporte el campo se declara como Float.
    # Redefinirlo como Monetary revienta el setup con "unknown currency_field None".
    value_report = fields.Float(groups=COST_GROUP)
