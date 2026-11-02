# -*- coding: utf-8 -*-
"""Cada solicitud de reabastecimiento arma su propio circuito (individualización con WIS).

Como en Forum: la preparación sale de Existencias del central a su Salida (MTS) y el envío
va de la Salida a la sucursal (MTO). Sin grupo, la segunda solicitud para la misma sucursal
se sumaba a la preparación y al envío abiertos de la primera.
"""
from odoo.tests.common import TransactionCase, tagged

from ..models.reposicion_proceso import PARAM_UMBRAL


@tagged('post_install', '-at_install', 'forum_reposicion')
class TestGrupoPorSolicitud(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        Almacen = cls.env['stock.warehouse']
        cls.sucursal = Almacen.create({'name': 'Sucursal grupo', 'code': 'GSU'})
        cls.central = Almacen.create({'name': 'Central grupo', 'code': 'GCE'})
        cls.salida = cls.env['stock.location'].create({
            'name': 'Salida GSU', 'usage': 'internal',
            'location_id': cls.central.view_location_id.id})
        cls.tipo_prep = cls.central.int_type_id
        cls.tipo_envio = cls.central.out_type_id
        cls.ruta = cls.env['stock.route'].create({
            'name': 'Abastecer sucursal grupo', 'product_selectable': True,
            'supplier_wh_id': cls.central.id, 'supplied_wh_id': cls.sucursal.id,
            'rule_ids': [
                (0, 0, {'name': 'Envío', 'action': 'pull', 'procure_method': 'make_to_order',
                        'location_src_id': cls.salida.id,
                        'location_dest_id': cls.sucursal.lot_stock_id.id,
                        'picking_type_id': cls.tipo_envio.id}),
                (0, 0, {'name': 'Preparación', 'action': 'pull',
                        'procure_method': 'make_to_stock',
                        'location_src_id': cls.central.lot_stock_id.id,
                        'location_dest_id': cls.salida.id,
                        'picking_type_id': cls.tipo_prep.id}),
            ]})
        Producto = cls.env['product.product']
        cls.productos = Producto.create([{'name': 'Remera grupo %s' % i, 'type': 'product',
                                          'route_ids': [(6, 0, cls.ruta.ids)]}
                                         for i in range(4)])
        for producto in cls.productos:
            cls.env['stock.quant']._update_available_quantity(
                producto, cls.central.lot_stock_id, 100)
        cls.reglas = cls.env['stock.warehouse.orderpoint'].create([{
            'product_id': p.id, 'location_id': cls.sucursal.lot_stock_id.id,
            'warehouse_id': cls.sucursal.id, 'trigger': 'manual', 'route_id': cls.ruta.id,
            'product_min_qty': 5, 'product_max_qty': 10,
        } for p in cls.productos])
        cls.Proceso = cls.env['forum.reposicion.proceso']

    def _operaciones(self, tipo):
        return self.env['stock.picking'].search([
            ('picking_type_id', '=', tipo.id),
            ('product_id', 'in', self.productos.ids)])

    def _umbral(self, valor):
        self.env['ir.config_parameter'].sudo().set_param(PARAM_UMBRAL, str(valor))

    def test_01_dos_solicitudes_dos_circuitos(self):
        """El ejemplo del documento: dos «Reabastecer» seguidos para la misma sucursal."""
        self._umbral(1000)
        self.reglas[:2].action_replenish()
        self.reglas[2:].action_replenish()
        preparaciones = self._operaciones(self.tipo_prep)
        envios = self._operaciones(self.tipo_envio)
        self.assertEqual(len(preparaciones), 2)
        self.assertEqual(len(envios), 2)
        self.assertEqual(len(preparaciones.group_id), 2)
        for prep in preparaciones:
            envio = envios.filtered(lambda e: e.group_id == prep.group_id)
            self.assertEqual(envio.move_ids.product_id, prep.move_ids.product_id,
                             'El envío lleva lo mismo que su preparación.')
            self.assertEqual(envio.move_ids.move_orig_ids.picking_id, prep)

    def test_02_la_recepcion_es_por_solicitud(self):
        """El grupo llega hasta el final del circuito (decisión de Daryl, 02-11-2026)."""
        self._umbral(1000)
        self.reglas[:2].action_replenish()
        envio = self._operaciones(self.tipo_envio)
        self.assertTrue(envio.group_id)
        self.assertEqual(envio.move_ids.group_id, envio.group_id)

    def test_03_un_proceso_en_segundo_plano_es_una_solicitud(self):
        self._umbral(1)
        self.reglas.action_replenish()
        proceso = self.Proceso.search([], limit=1)
        self.assertTrue(proceso.group_id)
        self.Proceso._correr_tanda(self.Proceso._token())
        preparaciones = self._operaciones(self.tipo_prep)
        envios = self._operaciones(self.tipo_envio)
        self.assertEqual(len(preparaciones), 1)
        self.assertEqual(len(envios), 1)
        self.assertEqual(preparaciones.group_id, proceso.group_id)
        self.assertEqual(envios.group_id, proceso.group_id)
        self.assertEqual(preparaciones.move_ids.product_id, self.productos)

    def test_04_la_regla_con_grupo_propio_lo_conserva(self):
        self._umbral(1000)
        grupo = self.env['procurement.group'].create({'name': 'Grupo de la regla'})
        self.reglas[0].group_id = grupo
        self.reglas[0].action_replenish()
        self.assertEqual(self._operaciones(self.tipo_prep).group_id, grupo)
