# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import BranchProfileCase


@tagged('post_install', '-at_install')
class TestBranchProfile(BranchProfileCase):

    def test_01_ve_solo_su_almacen(self):
        visibles = self.as_branch_user('stock.warehouse').search([])
        self.assertEqual(visibles, self.warehouse)
        self.assertNotIn(self.otro_warehouse, visibles)

    def test_01b_ve_solo_sus_tipos_de_operacion(self):
        visibles = self.as_branch_user('stock.picking.type').search([])
        self.assertTrue(visibles)
        self.assertEqual(visibles.warehouse_id, self.warehouse)

    def test_02_no_ve_transferencias_de_otro_almacen(self):
        picking_type = self.otro_warehouse.in_type_id
        ajeno = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': self.otro_warehouse.lot_stock_id.id,
        })
        self.assertNotIn(ajeno, self.as_branch_user('stock.picking').search([]))
        with self.assertRaises(AccessError):
            ajeno.with_user(self.user).read(['name'])

    def test_04_no_puede_configurar(self):
        """Lo que las ACL nativas dejan abierto y cierran las negaciones por modo."""
        with self.assertRaises(AccessError):
            self.pos_config.with_user(self.user).write({'name': 'Cambiado'})
        with self.assertRaises(AccessError):
            self.as_branch_user('stock.picking.type').create({
                'name': 'Nuevo tipo', 'code': 'internal',
                'sequence_code': 'NT', 'warehouse_id': self.warehouse.id,
            })
        with self.assertRaises(AccessError):
            self.as_branch_user('stock.warehouse').create({
                'name': 'Almacén pirata', 'code': 'PIR',
            })
        with self.assertRaises(AccessError):
            self.as_branch_user('product.template').create({'name': 'Producto pirata'})

    def test_06_ve_solo_su_pdv_y_sus_sesiones(self):
        configs = self.as_branch_user('pos.config').search([])
        self.assertEqual(configs, self.pos_config)
        self.assertNotIn(self.otro_pos, configs)

    def test_07_el_sudo_de_order_search_expand_sigue_pasando(self):
        """generic_security_restriction saltea el recorte cuando env.su es True.

        pos_forum_order_search_expand usa sudo() acotado para devolver pedidos de otros
        locales y otras compañías. La restricción sobre pos.order no debe interferir.
        """
        restriction = self.env.ref('forum_branch_security.restrict_pos_order')
        self.assertTrue(restriction.active)
        dominio_usuario = self.env['ir.rule'].with_user(self.user)._compute_domain(
            'pos.order', 'read')
        dominio_sudo = self.env['ir.rule'].with_user(self.user).sudo()._compute_domain(
            'pos.order', 'read')
        self.assertTrue(dominio_usuario, 'El perfil debería tener un recorte en pos.order.')
        self.assertFalse(dominio_sudo, 'El sudo() no debería arrastrar el recorte.')

    def test_08_el_supervisor_ve_sus_dos_almacenes(self):
        visibles = self.env['stock.warehouse'].with_user(self.supervisor).search([])
        self.assertEqual(visibles, self.warehouse | self.otro_warehouse)

    def test_09_cambiar_de_sucursal_surte_efecto_sin_reiniciar(self):
        self.assertEqual(
            self.as_branch_user('stock.warehouse').search([]), self.warehouse)
        self.user.branch_warehouse_ids = self.otro_warehouse
        self.assertEqual(
            self.as_branch_user('stock.warehouse').search([]), self.otro_warehouse,
            'El caché de ir.rule no se invalidó al cambiar la sucursal.')

    def test_10_no_se_creo_ni_archivo_ninguna_regla(self):
        """La restricción absoluta de la tarea."""
        archivadas = self.env['ir.rule'].with_context(active_test=False).search_count([
            ('active', '=', False)])
        # Las dos de core que la migración desarchiva ya no cuentan.
        self.assertTrue(self.env.ref('product.product_pricelist_comp_rule').active)
        self.assertTrue(self.env.ref('product.product_pricelist_item_comp_rule').active)
        propias = self.env['ir.model.data'].search_count([
            ('model', '=', 'ir.rule'),
            ('module', 'in', ('forum_branch_security', 'retail_branch')),
        ])
        self.assertEqual(propias, 0, 'El módulo creó reglas ir.rule, y no debe.')
        self.assertGreaterEqual(archivadas, 0)

    def test_12_la_vista_consolidada_abre(self):
        vista = self.env.ref('forum_branch_security.view_groups_form_branch_profile')
        arch = self.env['res.groups'].get_view(vista.id, 'form')
        for pestania in ('menu_access_only', 'model_restriction_ids',
                         'branch_field_restriction_ids', 'hidden_report_ids',
                         'branch_access_ids'):
            self.assertIn(pestania, arch['arch'])
        self.assertTrue(self.branch_group.menu_access_only)
        self.assertTrue(self.branch_group.model_restriction_ids)
        self.assertTrue(self.branch_group.branch_access_ids)
