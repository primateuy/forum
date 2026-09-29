# Copyright 2024 - TODAY, Wesley Oliveira <wesley.oliveira@escodoo.com.br>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase, tagged


# post_install: al instalar este módulo todavía no cargaron los que agregan
# campos obligatorios a product.template en la base de Forum.
@tagged("post_install", "-at_install")
class TestExcludeLocation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        # limit=1: el original suponía un almacén por compañía (Forum tiene 48).
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
        cls.location_1 = cls.env["stock.location"].create(
            {
                "company_id": cls.company.id,
                "location_id": cls.warehouse.lot_stock_id.id,
                "name": "Location 1",
            }
        )
        cls.location_2 = cls.env["stock.location"].create(
            {
                "company_id": cls.company.id,
                "location_id": cls.warehouse.lot_stock_id.id,
                "name": "Location 2",
            }
        )
        cls.sub_location_1 = cls.env["stock.location"].create(
            {
                "company_id": cls.company.id,
                "location_id": cls.location_1.id,
                "name": "Sub Location 1",
            }
        )
        cls.sub_location_2 = cls.env["stock.location"].create(
            {
                "company_id": cls.company.id,
                "location_id": cls.location_2.id,
                "name": "Sub Location 2",
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Test Product",
                "type": "product",
            }
        )

    def _add_stock_to_product(self, product, location, qty):
        """
        Set the stock quantity of the product
        :param product: product.product recordset
        :param location: stock.location recordset
        :param qty: float
        """
        self.env["stock.quant"].create(
            {
                "product_id": product.id,
                "location_id": location.id,
                "quantity": qty,
            }
        )

    def test_exclude_location(self):
        # Add stock for the product and query product stock availability normally.
        self.company.stock_excluded_location_ids = False
        self._add_stock_to_product(self.product, self.location_1, 50.0)
        self._add_stock_to_product(self.product, self.sub_location_1, 20.0)
        self._add_stock_to_product(self.product, self.location_2, 20.0)
        self._add_stock_to_product(self.product, self.sub_location_2, 10.0)
        self.assertEqual(self.product.qty_available, 100)

        # Add location_2 as an excluded location in the company, so location_2
        # and his child sub_location_2 are excluded from product availability.
        self.company.stock_excluded_location_ids = self.location_2
        self.product._compute_excluded_location_ids()
        self.product._compute_quantities()
        self.assertEqual(self.product.qty_available, 70)

    # --- Forum, 29-09-2026: el cálculo nuevo da lo mismo que el original ----
    def _excluidas_original(self, products):
        """El algoritmo original de OCA, tal cual, para comparar."""
        resultado = {}
        stock_quants = self.env["stock.quant"].search(
            [("product_id", "in", products.ids), ("on_hand", "=", True)]
        )
        for product in products:
            resultado[product.id] = self.env["stock.location"]
            product_quants = stock_quants.filtered(lambda x: x.product_id == product)
            if product_quants:
                company_ids = product_quants.mapped(lambda x: x.company_id)
                excluded_ids = company_ids.mapped(lambda x: x.stock_excluded_location_ids)
                if excluded_ids:
                    for excluded_location in excluded_ids:
                        excluded_ids |= excluded_location.children_ids
                    resultado[product.id] = excluded_ids
        return resultado

    def test_mismo_resultado_que_el_original(self):
        otros = self.env["product.product"].create(
            [{"name": "Prueba %d" % i, "type": "product"} for i in range(4)]
        )
        self._add_stock_to_product(otros[0], self.location_1, 5.0)
        self._add_stock_to_product(otros[1], self.sub_location_2, 3.0)
        self._add_stock_to_product(otros[2], self.location_2, 7.0)
        self._add_stock_to_product(otros[2], self.sub_location_1, 1.0)
        # otros[3] sin stock: no lleva exclusiones
        self._add_stock_to_product(self.product, self.location_1, 10.0)
        todos = self.product | otros
        for excluidas in (False, self.location_2, self.location_1 | self.location_2):
            self.company.stock_excluded_location_ids = excluidas
            todos.invalidate_recordset(["excluded_location_ids"])
            todos._compute_excluded_location_ids()
            esperado = self._excluidas_original(todos)
            for product in todos:
                self.assertEqual(product.excluded_location_ids, esperado[product.id],
                                 "%s con exclusiones %s" % (product.name, excluidas))
        self.assertFalse(otros[3].excluded_location_ids)

    def test_las_consultas_no_crecen_con_las_variantes(self):
        """🔴 La causa del listado que no cargaba era recorrer todos los quants
        por cada variante. Ahora es una consulta agrupada: la cantidad de
        consultas no depende de cuántas variantes se calculen."""
        self.company.stock_excluded_location_ids = self.location_2
        productos = self.env["product.product"].create(
            [{"name": "Volumen %d" % i, "type": "product"} for i in range(40)]
        )
        for product in productos:
            self._add_stock_to_product(product, self.location_1, 1.0)
            self._add_stock_to_product(product, self.location_2, 1.0)

        def contar(lote):
            # Se pide el campo como lo pide la vista: el cálculo corre
            # protegido. Llamar al método directo convierte cada asignación en
            # un write por variante y mide otra cosa.
            self.env.invalidate_all()
            antes = self.env.cr.sql_log_count
            lote.mapped("excluded_location_ids")
            return self.env.cr.sql_log_count - antes

        contar(productos[:5])     # calienta cachés (grupos, almacenes)
        self.assertEqual(contar(productos[:10]), contar(productos))
        self.assertEqual(productos[0].excluded_location_ids,
                         self.location_2 | self.location_2.children_ids)
