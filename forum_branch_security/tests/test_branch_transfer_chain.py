# -*- coding: utf-8 -*-
"""Envío entre sucursales con el perfil de sucursal (Forum, 2026-10-20).

El local manda mercadería a otra sucursal con «Intercambio - Envíos». La ruta de la
sucursal destino tiene dos reglas push:

    Salida X  → Tránsito X           automática, sin paso agregado
    Tránsito X → X/Existencias       manual, en un tipo de operación de X

Odoo crea el movimiento encadenado como superusuario, pero lo confirmaba con el
usuario que apretó «Marcar por realizar». El perfil no le deja leer las ubicaciones,
movimientos ni tipos de operación de la otra sucursal, y cortaba con AccessError sobre
X/Existencias (stock.location 110 en support).
"""
from odoo.tests import tagged

from .common import BranchProfileCase


@tagged('post_install', '-at_install')
class TestBranchTransferChain(BranchProfileCase):
    """Salida de tránsito."""

    SALIDA_INTERNA = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        empresa = cls.casa_central
        # En Forum el usuario del local está en la misma compañía que las ubicaciones:
        # con otra compañía activa Odoo ni siquiera busca las reglas push del almacén.
        cls.usuario_local = cls.env['res.users'].create({
            'name': 'Local Envío BP', 'login': 'local.envio.bp',
            'company_id': empresa.id,
            'company_ids': [(6, 0, [empresa.id])],
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.branch_group.id,
            ])],
        })
        cls.usuario_local.branch_warehouse_ids = cls.warehouse

        Location = cls.env['stock.location']
        padre_transito = cls.env.ref('stock.stock_location_locations_virtual')
        if cls.SALIDA_INTERNA:
            # Como en producción: POLO/Salida X, interna del Centro Logístico, que no
            # es ni el almacén del local ni el de la sucursal destino.
            cls.polo = cls.env['stock.warehouse'].create({
                'name': 'Centro Logístico BP', 'code': 'CLBP', 'company_id': empresa.id,
            })
            cls.salida = Location.create({
                'name': 'Salida Otro BP', 'usage': 'internal',
                'location_id': cls.polo.view_location_id.id, 'company_id': empresa.id,
            })
        else:
            cls.salida = Location.create({
                'name': 'Salida Otro BP', 'usage': 'transit',
                'location_id': padre_transito.id, 'company_id': empresa.id,
            })
        cls.transito = Location.create({
            'name': 'Tránsito Otro BP', 'usage': 'transit',
            'location_id': padre_transito.id, 'company_id': empresa.id,
        })
        cls.destino = cls.otro_warehouse.lot_stock_id

        cls.ruta = cls.env['stock.route'].create({
            'name': 'Otro BP: Recibe de Sucursal',
            'company_id': empresa.id,
            'warehouse_selectable': True,
            'warehouse_ids': [(6, 0, [cls.warehouse.id])],
            'rule_ids': [
                (0, 0, {
                    'name': 'Salida → Tránsito', 'action': 'push', 'auto': 'transparent',
                    'location_src_id': cls.salida.id, 'location_dest_id': cls.transito.id,
                    'picking_type_id': cls.warehouse.int_type_id.id,
                    'company_id': empresa.id,
                }),
                (0, 0, {
                    'name': 'Tránsito → Existencias', 'action': 'push', 'auto': 'manual',
                    'location_src_id': cls.transito.id, 'location_dest_id': cls.destino.id,
                    'picking_type_id': cls.otro_warehouse.int_type_id.id,
                    'company_id': empresa.id,
                }),
            ],
        })
        cls.producto = cls.env['product.product'].create({
            'name': 'Remera envío BP', 'type': 'product', 'company_id': False,
        })
        cls.env['stock.quant']._update_available_quantity(
            cls.producto, cls.warehouse.lot_stock_id, 10)

    def _envio(self):
        # Sin esto la regla y sus ubicaciones quedan en caché desde el setUpClass y el
        # error de permisos no aparece: en la vida real se leen de la base.
        self.env.invalidate_all()
        Picking = self.env['stock.picking'].with_user(self.usuario_local)
        return Picking.create({
            'picking_type_id': self.warehouse.out_type_id.id,
            'location_id': self.warehouse.lot_stock_id.id,
            'location_dest_id': self.salida.id,
            'move_ids': [(0, 0, {
                'name': self.producto.name, 'product_id': self.producto.id,
                'product_uom_qty': 4, 'product_uom': self.producto.uom_id.id,
                'location_id': self.warehouse.lot_stock_id.id,
                'location_dest_id': self.salida.id,
            })],
        })

    def _recepcion(self, envio):
        return envio.sudo().move_ids.move_dest_ids

    def test_01_marcar_por_realizar_encadena_la_recepcion(self):
        envio = self._envio()
        envio.action_confirm()

        movimiento = envio.sudo().move_ids
        self.assertEqual(movimiento.location_dest_id, self.transito,
                         'La regla automática lleva el envío hasta Tránsito.')
        recepcion = self._recepcion(envio)
        self.assertEqual(len(recepcion), 1)
        self.assertEqual(recepcion.location_id, self.transito)
        self.assertEqual(recepcion.location_dest_id, self.destino)
        self.assertEqual(recepcion.picking_id.picking_type_id, self.otro_warehouse.int_type_id)
        self.assertEqual(recepcion.state, 'waiting')
        # La transferencia de la otra sucursal la crea el usuario, aunque no la vea.
        self.assertEqual(recepcion.picking_id.create_uid, self.usuario_local)

    def test_02_el_perfil_sigue_sin_ver_la_otra_sucursal(self):
        envio = self._envio()
        envio.action_confirm()
        recepcion = self._recepcion(envio)
        self.assertFalse(
            self.env['stock.picking'].with_user(self.usuario_local).search(
                [('id', '=', recepcion.picking_id.id)]))
        self.assertFalse(
            self.env['stock.location'].with_user(self.usuario_local).search(
                [('id', '=', self.destino.id)]))

    def test_03_validar_el_envio_deja_lista_la_recepcion(self):
        envio = self._envio()
        envio.action_confirm()
        envio.action_assign()
        self.assertEqual(envio.state, 'assigned')
        envio.move_ids.quantity = 4
        envio.move_ids.picked = True
        envio.button_validate()
        self.assertEqual(envio.state, 'done')

        recepcion = self._recepcion(envio)
        self.assertEqual(recepcion.state, 'assigned',
                         'Con la mercadería en Tránsito, la recepción queda lista.')

    def test_04_ve_la_salida_para_elegirla_en_el_envio(self):
        self.assertTrue(
            self.env['stock.location'].with_user(self.usuario_local).search(
                [('id', '=', self.salida.id)]))


@tagged('post_install', '-at_install')
class TestBranchTransferChainSalidaInterna(TestBranchTransferChain):
    """Salida interna del Centro Logístico: la configuración de producción."""

    SALIDA_INTERNA = True

    def test_05_del_centro_logistico_ve_la_salida_y_nada_mas(self):
        Location = self.env['stock.location'].with_user(self.usuario_local)
        self.assertFalse(Location.search([('id', '=', self.polo.lot_stock_id.id)]))
        self.assertEqual(
            Location.search([('id', 'child_of', self.polo.view_location_id.id)]),
            self.salida)
