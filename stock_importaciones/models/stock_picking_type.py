# -*- coding: utf-8 -*-
from odoo import models, fields


class StockPickingType(models.Model):
    _inherit = "stock.picking.type"
    is_import_op = fields.Boolean(string='Op. de Importación')