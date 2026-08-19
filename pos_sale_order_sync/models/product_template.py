from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    excluir_logica_franquicia = fields.Boolean(
        'Excluir lógica franquicia',
        compute='_compute_excluir_logica_franquicia',
        store=True, readonly=False, precompute=True,
        help="Si está marcado, el producto no se copia a la orden de venta que se genera "
             "en la matriz a partir del ticket del POS de la franquicia.\n"
             "Viene marcado por defecto en los productos que no son almacenables "
             "(servicios, consumibles), y se puede desmarcar a mano.")

    @api.depends('type')
    def _compute_excluir_logica_franquicia(self):
        """Por defecto se excluye todo lo que no sea almacenable.

        Es un compute con `readonly=False`, así que el valor se puede cambiar a
        mano y queda guardado; solo se recalcula si cambia el tipo de producto.
        """
        for template in self:
            template.excluir_logica_franquicia = template.type != 'product'
