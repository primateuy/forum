# -*- coding: utf-8 -*-
"""Recepción demorada por una salida de POLO (support, Suc. Centro, 02-11-2026).

La lista de «Recepcion desde Deposito Central» caía con «no tiene acceso 'leer' a
Transferir»: el aviso de demora (`json_popover`) lee el nombre de la salida de POLO que
demora la recepción, y el perfil de sucursal no la ve.
"""
import json
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from .common import BranchProfileCase


@tagged('post_install', '-at_install')
class TestReceptionDelayPopover(BranchProfileCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        empresa = cls.casa_central
        cls.usuario_local = cls.env['res.users'].create({
            'name': 'Local Recepción BP', 'login': 'local.recepcion.bp',
            'company_id': empresa.id,
            'company_ids': [(6, 0, [empresa.id])],
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.branch_group.id,
            ])],
        })
        cls.usuario_local.branch_warehouse_ids = cls.warehouse
        cls.polo = cls.otro_warehouse
        cls.producto = cls.env['product.product'].create({
            'name': 'Remera recepción BP', 'type': 'product', 'company_id': False,
        })
        # Como «002/Transito a Centro»: el tránsito cuelga de la sucursal, así que el
        # movimiento de la salida se ve y su transferencia de POLO no.
        transito = cls.env['stock.location'].create({
            'name': 'Tránsito Recepción BP', 'usage': 'transit',
            'location_id': cls.warehouse.view_location_id.id,
            'company_id': empresa.id,
        })
        hoy = fields.Datetime.now()
        cls.recepcion = cls._picking(cls.warehouse.in_type_id, transito,
                                     cls.warehouse.lot_stock_id, hoy)
        # La salida de POLO llega DESPUÉS de la fecha prevista de la recepción.
        cls.salida = cls._picking(cls.polo.out_type_id, cls.polo.lot_stock_id,
                                  transito, hoy + timedelta(days=3))
        cls.salida.move_ids.move_dest_ids = cls.recepcion.move_ids
        cls.salida.with_company(empresa).action_confirm()
        cls.recepcion.with_company(empresa).action_confirm()

    @classmethod
    def _picking(cls, tipo, origen, destino, fecha):
        empresa = tipo.company_id
        return cls.env['stock.picking'].with_company(empresa).create({
            'company_id': empresa.id,
            'picking_type_id': tipo.id,
            'location_id': origen.id,
            'location_dest_id': destino.id,
            'scheduled_date': fecha,
            'move_ids': [(0, 0, {
                'name': cls.producto.name, 'product_id': cls.producto.id,
                'product_uom_qty': 3, 'product_uom': cls.producto.uom_id.id,
                'location_id': origen.id, 'location_dest_id': destino.id,
                'date': fecha, 'company_id': empresa.id,
            })],
        })

    def test_01_la_recepcion_esta_demorada_por_la_salida_de_polo(self):
        """Sin esto el resto no prueba nada: el aviso tiene que existir."""
        self.assertTrue(self.recepcion.delay_alert_date)
        datos = json.loads(self.recepcion.json_popover)
        self.assertIn(self.salida.id, [e['id'] for e in datos['late_elements']])

    def test_02_la_sucursal_lee_su_recepcion_demorada(self):
        self.env.invalidate_all()
        recepcion = self.env['stock.picking'].with_user(self.usuario_local).browse(
            self.recepcion.id)
        datos = json.loads(recepcion.json_popover)
        self.assertTrue(datos['delay_alert_date'])
        self.assertNotIn(self.salida.id, [e['id'] for e in datos['late_elements']],
                         'La salida de POLO no se lista: la sucursal no la puede abrir.')

    def test_03_sigue_sin_ver_la_salida_de_polo(self):
        self.assertFalse(self.env['stock.picking'].with_user(self.usuario_local).search(
            [('id', '=', self.salida.id)]))
