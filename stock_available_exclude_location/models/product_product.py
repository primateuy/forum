# Copyright 2024 - TODAY, Wesley Oliveira <wesley.oliveira@escodoo.com.br>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from collections import defaultdict

from odoo import api, fields, models


class ProductProduct(models.Model):

    _inherit = "product.product"

    excluded_location_ids = fields.Many2many(
        comodel_name="stock.location",
        string="Locations to Exclude as Available",
        compute="_compute_excluded_location_ids",
        readonly=True,
    )

    @api.depends()
    def _compute_excluded_location_ids(self):
        """Ubicaciones excluidas de la disponibilidad, por variante.

        🔴 Desvío del original de OCA (Forum, 29-09-2026). El original traía a
        memoria TODOS los quants en mano de las variantes y, para cada variante,
        los recorría todos (`stock_quants.filtered(lambda x: x.product_id ==
        product)`): variantes × quants en Python. Con los 869.000 quants de la
        carga de inventario, una página del listado de productos eran 2.571
        variantes × 86.547 quants ≈ 222 millones de comparaciones, ~170 s por
        pedido, y el listado no cargaba.

        Mismo resultado, costo lineal: el resultado sólo depende de QUÉ
        compañías tienen los quants en mano de cada variante, así que eso se
        pide agrupado a la base (mismo dominio, mismas reglas de acceso) y las
        ubicaciones excluidas se calculan una vez por combinación de compañías.
        """
        self.update({"excluded_location_ids": False})
        ids = [product_id for product_id in self.ids if product_id]
        if not ids:
            return
        grupos = self.env["stock.quant"]._read_group(
            [("product_id", "in", ids), ("on_hand", "=", True)],
            groupby=["product_id", "company_id"],
        )
        companias_por_producto = defaultdict(set)
        for product, company in grupos:
            # Un quant sin compañía no aporta ubicaciones excluidas (igual que
            # antes: `mapped` sobre una compañía vacía no devuelve nada).
            companias_por_producto[product.id].add(company.id or 0)
        excluidas_por_companias = {}
        for product in self:
            companias = companias_por_producto.get(product.id)
            if not companias:
                continue
            clave = frozenset(companias)
            if clave not in excluidas_por_companias:
                companies = self.env["res.company"].browse(sorted(c for c in clave if c))
                excluded_ids = companies.mapped(lambda x: x.stock_excluded_location_ids)
                for excluded_location in excluded_ids:
                    excluded_ids |= excluded_location.children_ids
                excluidas_por_companias[clave] = excluded_ids
            if excluidas_por_companias[clave]:
                product.excluded_location_ids = excluidas_por_companias[clave]

    def _compute_quantities_dict(
        self, lot_id, owner_id, package_id, from_date=False, to_date=False
    ):
        context = dict(
            self.env.context, excluded_location_ids=self.excluded_location_ids
        )
        return super(
            ProductProduct, self.with_context(**context)
        )._compute_quantities_dict(lot_id, owner_id, package_id, from_date, to_date)
