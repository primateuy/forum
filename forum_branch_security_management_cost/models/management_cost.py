# -*- coding: utf-8 -*-
"""El costo de gestión, bajo el mismo grupo que el resto de los costos."""
from odoo import models, fields

COST_GROUP = 'forum_branch_security.group_product_cost'


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    management_cost = fields.Float(groups=COST_GROUP)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    management_cost = fields.Float(groups=COST_GROUP)


class StockQuantProductLocationReport(models.Model):
    """Las dos columnas que el módulo agrega a la Consulta de Stock, más el TC.

    Van en el SELECT de la vista SQL y no como campo calculado —porque un campo calculado
    no totaliza en las agrupaciones—, así que son campos reales del modelo y `groups=`
    los cubre igual.
    """
    _inherit = 'stock.quant.product.location.report'

    management_cost = fields.Float(groups=COST_GROUP)
    management_value = fields.Float(groups=COST_GROUP)
    management_rate = fields.Float(groups=COST_GROUP)
