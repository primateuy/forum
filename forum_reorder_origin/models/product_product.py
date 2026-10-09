# -*- coding: utf-8 -*-
from odoo import models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _get_rules_from_location(self, location, route_ids=False, seen_rules=False):
        """Durante la regeneración del informe de reabastecimiento, una búsqueda por ruta.

        El core busca la regla de cada par (producto, ubicación) con saldo negativo —miles—
        para sacar los días de entrega. La búsqueda sólo depende de las rutas del producto
        (las suyas y las de su categoría), de la ubicación y de las rutas pedidas: las
        variantes de una misma plantilla dan siempre lo mismo. Fuera del informe, sin caché.
        """
        if not self.env.context.get('forum_reporte_rapido') or len(self) != 1:
            return super()._get_rules_from_location(
                location, route_ids=route_ids, seen_rules=seen_rules)
        rutas = (self.route_ids | self.categ_id.total_route_ids).ids
        clave = (tuple(sorted(rutas)), location.id,
                 tuple(route_ids.ids) if route_ids else (),
                 tuple(seen_rules.ids) if seen_rules else ())
        cache = self.env.cr.cache.setdefault('forum_reporte_reglas', {})
        if clave not in cache:
            cache[clave] = super()._get_rules_from_location(
                location, route_ids=route_ids, seen_rules=seen_rules).ids
        return self.env['stock.rule'].browse(cache[clave])
