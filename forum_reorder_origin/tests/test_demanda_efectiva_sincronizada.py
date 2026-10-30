# -*- coding: utf-8 -*-
"""La «Demanda a considerar» sigue a la cantidad a pedir (Forum, 30-10-2026).

Reabasteciendo Jean Slim Fit, el filtro «Reglas cumplibles» mostraba reglas con el origen
sin stock y «Reponer al máximo» las rechazaba con «Stock insuficiente en origen». El filtro
agrupa por `forum_demand_effective` y el control por `qty_to_order`: cuando el core
recalculaba `qty_to_order` con `env.add_to_compute()` —lo que hace `stock.move` al cambiar—
la demanda efectiva quedaba vieja, muchas veces en 0, y la regla no entraba al cálculo.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from ..models.reposicion_proceso import PARAM_UMBRAL

CUMPLIBLES = [('origin_stock_warning', '=', False), ('qty_to_order', '>', 0),
              ('origin_warehouse_id', '!=', False)]


@tagged('post_install', '-at_install', 'forum_reposicion')
class TestDemandaEfectivaSincronizada(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.env['ir.config_parameter'].sudo().set_param(PARAM_UMBRAL, '200')
        cls.centro = cls.env['stock.warehouse'].create({'name': 'Centro demanda test',
                                                        'code': 'CDT'})
        cls.tienda = cls.env['stock.warehouse'].create({
            'name': 'Tienda demanda test', 'code': 'TDT',
            'resupply_wh_ids': [(6, 0, cls.centro.ids)]})
        cls.producto = cls.env['product.product'].create({
            'name': 'Jean demanda test', 'type': 'product',
            'route_ids': [(6, 0, cls.tienda.resupply_route_ids.ids)]})
        cls.op = cls.env['stock.warehouse.orderpoint'].create({
            'product_id': cls.producto.id, 'warehouse_id': cls.tienda.id,
            'location_id': cls.tienda.lot_stock_id.id, 'trigger': 'manual',
            'product_min_qty': 2, 'product_max_qty': 2})

    def _en_base(self):
        self.env.flush_all()
        self.env.cr.execute("""SELECT qty_to_order, forum_demand_effective
                                 FROM stock_warehouse_orderpoint WHERE id = %s""", [self.op.id])
        return self.env.cr.fetchone()

    def _recalcular_como_stock_move(self):
        """Lo que hace `stock.move` al cambiar: marca sólo `qty_to_order` para recalcular."""
        Orderpoint = self.env['stock.warehouse.orderpoint']
        self.env.invalidate_all()
        self.env.add_to_compute(Orderpoint._fields['qty_to_order'], self.op)

    def _subir_maximo_sin_orm(self, maximo):
        """Cambia el máximo sin pasar por el ORM, como un cambio que nadie avisó."""
        self.env.flush_all()
        self.env.cr.execute("""UPDATE stock_warehouse_orderpoint
                                  SET product_min_qty = %s, product_max_qty = %s
                                WHERE id = %s""", [maximo, maximo, self.op.id])

    def test_el_recalculo_del_core_arrastra_la_demanda_efectiva(self):
        self.assertEqual(self._en_base(), (2.0, 2.0))
        self._subir_maximo_sin_orm(12)
        self._recalcular_como_stock_move()
        self.assertEqual(self._en_base(), (12.0, 12.0))

    def test_regla_desfasada_en_cero_no_aparece_como_cumplible(self):
        # Así quedaban las reglas en las bases: demanda efectiva en 0 con cantidad a pedir.
        self.env.flush_all()
        self.env.cr.execute("UPDATE stock_warehouse_orderpoint SET forum_demand_effective = 0 "
                            "WHERE id = %s", [self.op.id])
        self._recalcular_como_stock_move()
        # Lo que hace la pantalla: buscar con el filtro. La búsqueda resuelve lo pendiente.
        Orderpoint = self.env['stock.warehouse.orderpoint']
        self.assertFalse(Orderpoint.search(CUMPLIBLES + [('id', '=', self.op.id)]),
                         "el origen no tiene stock: no es cumplible")
        self.assertTrue(Orderpoint.search([('origin_stock_warning', '=', True),
                                           ('id', '=', self.op.id)]))
        self.assertEqual(self._en_base(), (2.0, 2.0))

    def test_reponer_al_maximo_controla_la_cantidad_maxima(self):
        self.env['stock.quant']._update_available_quantity(
            self.producto, self.centro.lot_stock_id, 6)
        self.op.write({'product_min_qty': 5, 'product_max_qty': 10})
        self.op.qty_to_order = 5  # alcanza con 6 en el centro
        with self.assertRaisesRegex(UserError, 'Stock insuficiente en origen'):
            self.op.action_replenish(force_to_max=True)  # al máximo pide 10

    def test_reponer_al_maximo_que_alcanza_sigue_funcionando(self):
        self.env['stock.quant']._update_available_quantity(
            self.producto, self.centro.lot_stock_id, 20)
        self.op.write({'product_min_qty': 5, 'product_max_qty': 10})
        self.op.action_replenish(force_to_max=True)
        movimientos = self.env['stock.move'].search([
            ('product_id', '=', self.producto.id),
            ('location_dest_id', '=', self.tienda.lot_stock_id.id)])
        self.assertEqual(sum(movimientos.mapped('product_uom_qty')), 10)
