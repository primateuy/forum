from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    excluir_logica_franquicia = fields.Boolean('Excluir lógica franquicia', default=False)
