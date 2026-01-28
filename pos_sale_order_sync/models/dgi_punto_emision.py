from odoo import models, fields, api


class DgiPuntoEmision(models.Model):
    _inherit = "dgi.punto.emision"

    max_numero_lineas = fields.Integer('Cantidad máxima de líneas', default=199)
