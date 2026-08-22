# -*- coding: utf-8 -*-
import logging
import math

from odoo import api, models
from odoo.tools import float_compare, float_round

_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def forum_round_to_distribution_multiple(self, qty, max_qty=None):
        """Redondea una cantidad al múltiplo de distribución del producto.

        El múltiplo (``mutiplos_distribucion``, definido en automatic_crossdocking) es una
        restricción dura: no se puede mover 7 unidades si el producto viaja en packs de 6.
        Por eso el redondeo es siempre hacia arriba (ceil), independientemente del
        ``reorder_rounding_method`` global de advance.reordering.settings.

        :param qty: cantidad calculada a redondear.
        :param max_qty: tope opcional. Si el múltiplo hacia arriba lo supera, se baja al
            múltiplo inferior (floor de rescate). Se usa en el flujo IWT pasando el stock
            disponible en el almacén origen, para no generar una transferencia que después
            explote en action_assign por falta de stock.
        :return: cantidad redondeada al múltiplo, o 0.0 si ni el múltiplo inferior entra
            en el tope.
        """
        self.ensure_one()
        multiple = self.mutiplos_distribucion or 1
        if multiple <= 1 or qty <= 0:
            return qty

        rounding = self.uom_id.rounding or 0.01

        # float_round sobre el ratio evita que 6.0000001 / 6 escale a 2 múltiplos.
        ratio = float_round(qty / multiple, precision_digits=6)
        redondeada = math.ceil(ratio) * multiple

        if max_qty is not None and float_compare(redondeada, max_qty, precision_rounding=rounding) > 0:
            ratio_tope = float_round(max_qty / multiple, precision_digits=6)
            redondeada = math.floor(ratio_tope) * multiple

        return float(max(redondeada, 0.0))

    @api.model
    def forum_products_from_categories(self, categories, extra_domain=None):
        """Devuelve los productos de las categorías indicadas y de todas sus hijas.

        :param categories: recordset de product.category.
        :param extra_domain: dominio adicional a aplicar (filtros propios de cada flujo).
        :return: recordset de product.product.
        """
        if not categories:
            return self.browse()
        domain = [('categ_id', 'child_of', categories.ids)]
        if extra_domain:
            domain += extra_domain
        return self.search(domain)
