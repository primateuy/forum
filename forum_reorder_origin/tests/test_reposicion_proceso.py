# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user, tagged

from ..models.reposicion_proceso import PARAM_UMBRAL


@tagged('post_install', '-at_install', 'forum_reposicion')
class TestReposicionProceso(TransactionCase):
    """Reposición en segundo plano. En los tests no hay commit ni petición HTTP: la tanda se
    corre a mano con `_correr_tanda`, que es lo que haría la petición encadenada."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        Almacen = cls.env['stock.warehouse']
        cls.almacen = Almacen.create({'name': 'Sucursal reposición en fondo', 'code': 'RPS'})
        cls.central = Almacen.create({'name': 'Central reposición en fondo', 'code': 'RPC'})
        regla = {
            'name': 'Central → sucursal test', 'action': 'pull',
            'procure_method': 'make_to_stock',
            'location_src_id': cls.central.lot_stock_id.id,
            'location_dest_id': cls.almacen.lot_stock_id.id,
            'picking_type_id': cls.almacen.int_type_id.id,
        }
        cls.ruta = cls.env['stock.route'].create({
            'name': 'Abastecer sucursal proceso test', 'product_selectable': True,
            'supplier_wh_id': cls.central.id, 'supplied_wh_id': cls.almacen.id,
            'rule_ids': [(0, 0, regla)]})
        Producto = cls.env['product.product']
        cls.con_stock = Producto.create({'name': 'Con stock proceso', 'type': 'product',
                                         'route_ids': [(6, 0, cls.ruta.ids)]})
        cls.sin_stock = Producto.create({'name': 'Sin stock proceso', 'type': 'product',
                                         'route_ids': [(6, 0, cls.ruta.ids)]})
        cls.sin_ruta = Producto.create({'name': 'Sin ruta proceso', 'type': 'product',
                                        'route_ids': [(6, 0, [])]})
        cls.env['stock.quant']._update_available_quantity(
            cls.con_stock, cls.central.lot_stock_id, 100)
        Orderpoint = cls.env['stock.warehouse.orderpoint']
        cls.op_ok, cls.op_sin_stock = Orderpoint.create([{
            'product_id': p.id, 'location_id': cls.almacen.lot_stock_id.id,
            'warehouse_id': cls.almacen.id, 'trigger': 'manual', 'route_id': cls.ruta.id,
            'product_min_qty': 5, 'product_max_qty': 10,
        } for p in (cls.con_stock, cls.sin_stock)])
        cls.op_mal = Orderpoint.create({
            'product_id': cls.sin_ruta.id, 'location_id': cls.almacen.lot_stock_id.id,
            'warehouse_id': cls.almacen.id, 'trigger': 'manual',
            'product_min_qty': 5, 'product_max_qty': 10,
        })
        cls.todas = cls.op_ok | cls.op_sin_stock | cls.op_mal
        cls.env['ir.config_parameter'].sudo().set_param(PARAM_UMBRAL, '1')
        cls.Proceso = cls.env['forum.reposicion.proceso']
        cls.previos = cls.Proceso.search([]).ids

    def _procesos(self):
        """Los procesos creados por el test, del más viejo al más nuevo."""
        return self.Proceso.search([('id', 'not in', self.previos)], order='id')

    def _moves(self, producto):
        return self.env['stock.move'].search([
            ('product_id', '=', producto.id),
            ('location_dest_id', '=', self.almacen.lot_stock_id.id)])

    def _correr(self):
        return self.Proceso._correr_tanda(self.Proceso._token())

    def _linea(self, proceso, producto):
        # Por producto: el core borra la regla manual que quedó en cero después de ordenar.
        return proceso.linea_ids.filtered(lambda l: l.product_id == producto)

    def test_el_boton_crea_el_proceso_y_no_repone(self):
        res = self.todas.action_replenish()
        self.assertEqual(res['tag'], 'display_notification')
        proceso = self._procesos()
        self.assertIn(proceso.name, res['params']['title'])
        self.assertTrue(proceso.name.startswith('REP/'))
        self.assertEqual((proceso.state, proceso.total, proceso.procesadas), ('cola', 3, 0))
        self.assertEqual(set(proceso.linea_ids.orderpoint_id.ids), set(self.todas.ids))
        self.assertFalse(self._moves(self.con_stock), "en la petición del usuario no se repone")

    def test_la_tanda_repone_saltea_y_lista(self):
        self.todas.action_replenish()
        proceso = self._procesos()
        self.assertEqual(self._correr(), {'estado': 'listo'})
        self.assertEqual(proceso.state, 'hecho')
        self.assertEqual((proceso.procesadas, proceso.repuestas, proceso.sin_stock, proceso.errores),
                         (3, 1, 1, 1))
        self.assertEqual(proceso.progress, 100.0)
        self.assertEqual(self._linea(proceso, self.con_stock).estado, 'repuesta')
        linea = self._linea(proceso, self.sin_stock)
        self.assertEqual(linea.estado, 'sin_stock')
        self.assertIn('Disponible en', linea.motivo)
        self.assertEqual(self._linea(proceso, self.sin_ruta).estado, 'error')
        self.assertTrue(self._linea(proceso, self.sin_ruta).motivo)
        # Lo repuesto queda anotado en el proceso; lo salteado no se movió.
        moves = self._moves(self.con_stock)
        self.assertEqual(sum(moves.mapped('product_uom_qty')), 10)
        self.assertEqual(proceso.picking_ids, moves.picking_id)
        self.assertEqual(proceso.picking_count, 1)
        self.assertFalse(self._moves(self.sin_stock))
        self.assertFalse(self._moves(self.sin_ruta))
        self.assertFalse(self.op_ok.exists(), "el core borra la regla manual que quedó en cero")
        problemas = proceso.action_ver_reglas_con_problema()
        self.assertEqual(set(problemas['domain'][0][2]), {self.op_sin_stock.id, self.op_mal.id})
        self.assertIn('Terminado', proceso.log)

    def test_al_maximo(self):
        self.env['stock.quant']._update_available_quantity(
            self.con_stock, self.almacen.lot_stock_id, 7)   # sobre el mínimo: no pide nada
        (self.op_ok | self.op_sin_stock).action_replenish(force_to_max=True)
        proceso = self._procesos()
        self.assertTrue(proceso.force_to_max)
        self._correr()
        self.assertEqual(self._linea(proceso, self.con_stock).estado, 'repuesta')
        self.assertEqual(sum(self._moves(self.con_stock).mapped('product_uom_qty')), 3)

    def test_no_se_repone_dos_veces(self):
        self.todas.action_replenish()
        (self.op_ok | self.op_sin_stock).action_replenish()
        primero, segundo = self._procesos()
        self.assertEqual(primero.total, 3)
        self.assertEqual(segundo.state, 'hecho', "nada nuevo para reponer")
        self.assertEqual((segundo.total, segundo.omitidas), (0, 2))
        self._correr()
        self.assertEqual(primero.state, 'hecho')
        self.assertEqual(sum(self._moves(self.con_stock).mapped('product_uom_qty')), 10)

    def test_por_dominio(self):
        Orderpoint = self.env['stock.warehouse.orderpoint']
        res = Orderpoint.forum_reponer_dominio([('id', 'in', self.todas.ids)])
        proceso = self._procesos()
        self.assertIn(proceso.name, res['params']['title'])
        self.assertEqual(proceso.total, 3)
        self.assertEqual(proceso.linea_ids.mapped('secuencia'), [1, 2, 3])

    def test_por_dominio_bajo_el_umbral_es_inmediato(self):
        self.env['ir.config_parameter'].sudo().set_param(PARAM_UMBRAL, '10')
        Orderpoint = self.env['stock.warehouse.orderpoint']
        Orderpoint.forum_reponer_dominio([('id', '=', self.op_ok.id)])
        self.assertFalse(self._procesos())
        self.assertTrue(self._moves(self.con_stock))

    def test_cancelar_y_reanudar(self):
        self.todas.action_replenish()
        proceso = self._procesos()
        proceso.action_cancelar()
        self.assertEqual(self._correr(), {'estado': 'listo'})
        self.assertEqual(proceso.procesadas, 0, "cancelado no se procesa")
        proceso.action_reanudar()
        self.assertEqual(proceso.state, 'cola')
        self._correr()
        self.assertEqual((proceso.state, proceso.repuestas), ('hecho', 1))

    def test_regla_borrada_se_omite(self):
        self.todas.action_replenish()
        proceso = self._procesos()
        self.op_mal.unlink()
        self._correr()
        self.assertEqual((proceso.repuestas, proceso.sin_stock, proceso.errores, proceso.omitidas),
                         (1, 1, 0, 1))

    def test_token_invalido(self):
        self.todas.action_replenish()
        self.assertEqual(self.Proceso._correr_tanda('otro'), {'estado': 'token inválido'})
        self.assertEqual(self._procesos().state, 'cola')


@tagged('post_install', '-at_install', 'forum_reposicion')
class TestReposicionPermisos(TestReposicionProceso):
    """El grupo «Reposición masiva» habilita el segundo plano y el menú; cada compañía ve lo suyo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.inventario = new_test_user(cls.env, 'rep_sin_grupo', groups='stock.group_stock_manager')
        cls.masivo = new_test_user(
            cls.env, 'rep_masivo', groups='stock.group_stock_manager,forum_reorder_origin.group_reposicion_masiva')
        otra = cls.env['res.company'].create({'name': 'Otra compañía reposición'})
        cls.masivo_otra = new_test_user(
            cls.env, 'rep_masivo_otra', company_id=otra.id, company_ids=[(6, 0, otra.ids)],
            groups='stock.group_stock_manager,forum_reorder_origin.group_reposicion_masiva')
        cls.menu = cls.env.ref('forum_reorder_origin.forum_reposicion_proceso_menu')

    def test_sin_grupo_no_ordena_masivo(self):
        with self.assertRaisesRegex(UserError, 'Reposición masiva'):
            self.todas.with_user(self.inventario).action_replenish()
        with self.assertRaisesRegex(UserError, 'Reposición masiva'):
            self.env['stock.warehouse.orderpoint'].with_user(self.inventario).forum_reponer_dominio(
                [('id', 'in', self.todas.ids)])
        self.assertFalse(self._procesos())

    def test_sin_grupo_hasta_el_umbral_ordena_como_siempre(self):
        self.env['ir.config_parameter'].sudo().set_param(PARAM_UMBRAL, '10')
        self.op_ok.with_user(self.inventario).action_replenish()
        self.assertFalse(self._procesos())
        self.assertTrue(self._moves(self.con_stock))

    def test_sin_grupo_no_ve_menu_ni_procesos(self):
        self.todas.with_user(self.masivo).action_replenish()
        proceso = self._procesos()
        self.assertEqual(proceso.user_id, self.masivo)
        Menu = self.env['ir.ui.menu']
        self.assertIn(self.menu.id, Menu.with_user(self.masivo)._visible_menu_ids())
        self.assertNotIn(self.menu.id, Menu.with_user(self.inventario)._visible_menu_ids())
        with self.assertRaises(AccessError):
            proceso.with_user(self.inventario).read(['name'])
        with self.assertRaises(AccessError):
            proceso.with_user(self.inventario).action_cancelar()

    def test_con_grupo_ve_y_cancela(self):
        self.todas.with_user(self.masivo).action_replenish()
        proceso = self._procesos().with_user(self.masivo)
        self.assertEqual(proceso.read(['total'])[0]['total'], 3)
        self.assertEqual(len(proceso.linea_ids), 3)
        proceso.action_cancelar()
        self.assertEqual(proceso.state, 'cancelado')

    def test_otra_compania_no_lo_ve(self):
        self.todas.with_user(self.masivo).action_replenish()
        Proceso = self.env['forum.reposicion.proceso'].with_user(self.masivo_otra)
        self.assertFalse(Proceso.search([('id', 'in', self._procesos().ids)]))
        self.assertFalse(self.env['forum.reposicion.proceso.regla'].with_user(self.masivo_otra).search(
            [('proceso_id', 'in', self._procesos().ids)]))
