# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.addons.stock.models.stock_orderpoint import StockWarehouseOrderpoint as OrderpointCore
from odoo.tests.common import TransactionCase, tagged

from ..models import stock_warehouse_orderpoint as modulo


@tagged('post_install', '-at_install', 'forum_reposicion')
class TestReposicionTolerante(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.almacen = cls.env['stock.warehouse'].create({'name': 'Sucursal reposición test',
                                                         'code': 'SRT'})
        cls.origen = cls.env['stock.location'].create({
            'name': 'Origen reposición test', 'usage': 'internal'})
        cls.ruta = cls.env['stock.route'].create({
            'name': 'Abastecer sucursal test', 'product_selectable': True,
            'rule_ids': [(0, 0, {
                'name': 'Origen → sucursal test', 'action': 'pull',
                'procure_method': 'make_to_stock',
                'location_src_id': cls.origen.id,
                'location_dest_id': cls.almacen.lot_stock_id.id,
                'picking_type_id': cls.almacen.int_type_id.id,
            })]})
        Producto = cls.env['product.product']
        cls.con_ruta = Producto.create({'name': 'Con ruta test', 'type': 'product',
                                        'route_ids': [(6, 0, cls.ruta.ids)]})
        cls.sin_ruta = Producto.create({'name': 'Sin ruta test', 'type': 'product',
                                        'route_ids': [(6, 0, [])]})
        Orderpoint = cls.env['stock.warehouse.orderpoint']
        cls.op_ok, cls.op_mal = Orderpoint.create([{
            'product_id': p.id, 'location_id': cls.almacen.lot_stock_id.id,
            'warehouse_id': cls.almacen.id, 'trigger': 'manual',
            'product_min_qty': 5, 'product_max_qty': 10,
        } for p in (cls.con_ruta, cls.sin_ruta)])

    def _moves(self, producto):
        return self.env['stock.move'].search([
            ('product_id', '=', producto.id),
            ('location_dest_id', '=', self.almacen.lot_stock_id.id)])

    def test_una_regla_sin_ruta_no_cancela_el_lote(self):
        res = (self.op_ok | self.op_mal).action_replenish()
        self.assertTrue(self._moves(self.con_ruta), "la que tiene ruta se ordenó")
        self.assertFalse(self._moves(self.sin_ruta))
        self.assertEqual(res['tag'], 'display_notification')
        self.assertEqual(res['params']['type'], 'warning')
        self.assertTrue(res['params']['sticky'])
        self.assertIn('1 de 2', res['params']['title'])
        self.assertIn('Sin ruta test', res['params']['message'])
        self.assertFalse(self.env.cr.cache.get('forum_reposicion_errores'))

    def test_una_sola_regla_mantiene_el_error_del_core(self):
        with self.assertRaises(Exception):
            self.op_mal.action_replenish()

    def test_filtro_sin_ruta(self):
        ids = (self.op_ok | self.op_mal).ids
        Orderpoint = self.env['stock.warehouse.orderpoint']
        self.assertEqual(Orderpoint.search([('id', 'in', ids), ('forum_sin_ruta', '=', True)]),
                         self.op_mal)
        self.assertEqual(Orderpoint.search([('id', 'in', ids), ('forum_sin_ruta', '=', False)]),
                         self.op_ok)
        self.assertTrue(self.op_mal.forum_sin_ruta)
        self.assertFalse(self.op_ok.forum_sin_ruta)
        # Por la ruta del almacén también llega.
        self.almacen.route_ids = [(4, self.ruta.id)]
        self.ruta.warehouse_selectable = True
        self.assertFalse(Orderpoint.search([('id', 'in', ids), ('forum_sin_ruta', '=', True)]))

    def test_el_informe_se_regenera_una_vez_por_ventana(self):
        modulo._REPORTE_ULTIMO.clear()
        Orderpoint = self.env['stock.warehouse.orderpoint']
        self.env['ir.config_parameter'].sudo().set_param('forum_reorder_origin.reporte_minutos', '10')
        with patch.object(OrderpointCore, '_get_orderpoint_action', autospec=True,
                          return_value={'type': 'ir.actions.act_window'}) as core:
            Orderpoint.action_open_orderpoints()
            accion = Orderpoint.action_open_orderpoints()
            self.assertEqual(core.call_count, 1)
            self.assertEqual(accion['res_model'], 'stock.warehouse.orderpoint')
            self.env['ir.config_parameter'].sudo().set_param(
                'forum_reorder_origin.reporte_minutos', '0')
            Orderpoint.action_open_orderpoints()
            self.assertEqual(core.call_count, 2, "con 0 se regenera siempre")
        modulo._REPORTE_ULTIMO.clear()

    def test_cumplibles_se_calcula_una_vez_por_peticion(self):
        Orderpoint = self.env['stock.warehouse.orderpoint']
        with patch.object(type(Orderpoint), '_origin_unfulfillable_ids', autospec=True,
                          return_value=set()) as calculo:
            Orderpoint.search([('origin_stock_warning', '=', False)], limit=1)
            Orderpoint.search_count([('origin_stock_warning', '=', False)])
            self.assertEqual(calculo.call_count, 1)
            self.op_ok.product_min_qty = 6
            Orderpoint.search([('origin_stock_warning', '=', True)], limit=1)
            self.assertEqual(calculo.call_count, 2, "escribir una regla descarta la caché")

    def test_agregar_ruta_de_sucursal(self):
        self.ruta.supplied_wh_id = self.almacen
        otra = self.env['stock.route'].create({'name': 'Otra ruta test', 'product_selectable': True})
        self.sin_ruta.route_ids = [(6, 0, otra.ids)]
        res = (self.op_ok | self.op_mal).action_agregar_ruta_sucursal()
        self.assertEqual(res['params']['type'], 'success')
        self.assertEqual(self.sin_ruta.route_ids, otra | self.ruta, "agrega, no reemplaza")
        self.assertFalse(self.op_mal.forum_sin_ruta)
        res = (self.op_ok | self.op_mal).action_replenish()
        self.assertFalse(res, "ya no hay reglas que fallen")

    def _foto_reglas(self, productos):
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT product_id, location_id, round(qty_to_order::numeric, 4), active
              FROM stock_warehouse_orderpoint WHERE product_id = ANY(%s)""", [productos.ids])
        return set(self.env.cr.fetchall())

    def test_el_informe_rapido_crea_lo_mismo_que_el_core(self):
        """El prefiltro de productos y la caché de reglas no cambian lo que crea el informe."""
        modulo._REPORTE_ULTIMO.clear()
        self.env['ir.config_parameter'].sudo().set_param('forum_reorder_origin.reporte_minutos', '0')
        Producto = self.env['product.product']
        negativos = Producto.create([{'name': 'Negativo informe %s' % i, 'type': 'product',
                                      'route_ids': [(6, 0, self.ruta.ids)]} for i in range(3)])
        positivo = Producto.create({'name': 'Positivo informe', 'type': 'product'})
        cliente = self.env.ref('stock.stock_location_customers')
        for producto, cantidad in zip(negativos, (2, 5, 9)):
            self.env['stock.move'].create({
                'name': 'salida', 'product_id': producto.id, 'product_uom_qty': cantidad,
                'product_uom': producto.uom_id.id, 'location_id': self.almacen.lot_stock_id.id,
                'location_dest_id': cliente.id})._action_confirm()
        self.env['stock.quant']._update_available_quantity(
            positivo, self.almacen.lot_stock_id, 4)
        todos = negativos | positivo
        Orderpoint = self.env['stock.warehouse.orderpoint']

        with self.env.cr.savepoint(flush=True) as sp:
            OrderpointCore._get_orderpoint_action(Orderpoint)
            core = self._foto_reglas(todos)
            sp.rollback()
        self.env.invalidate_all()
        Orderpoint._get_orderpoint_action()
        rapido = self._foto_reglas(todos)
        self.assertEqual(rapido, core)
        self.assertEqual({fila[0] for fila in core}, set(negativos.ids),
                         "la prueba tiene que crear reglas para los negativos y no para el positivo")
        modulo._REPORTE_ULTIMO.clear()
