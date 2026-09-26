# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import BranchProfileCase


@tagged('post_install', '-at_install')
class TestCostVisibility(BranchProfileCase):
    """El costo se oculta con groups= nativo, no con la capa de presentación.

    La diferencia importa: `invisible` inyectado en el arch no saca el campo de
    fields_get, así que en una vista pivot el usuario lo agrega como medida desde el
    desplegable. Con groups= el campo no existe para ese usuario.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.producto = cls.env['product.product'].create({
            'name': 'Producto BP', 'standard_price': 100.0, 'list_price': 250.0,
        })

    def test_05_el_perfil_no_ve_standard_price(self):
        campos = self.as_branch_user('product.template').fields_get()
        self.assertNotIn('standard_price', campos,
                         'standard_price sigue en fields_get para el perfil sucursal.')
        with self.assertRaises(AccessError):
            self.producto.with_user(self.user).read(['standard_price'])

    def test_05b_un_usuario_con_el_grupo_si_lo_ve(self):
        self.user.groups_id = [(4, self.cost_group.id)]
        campos = self.as_branch_user('product.template').fields_get()
        self.assertIn('standard_price', campos)

    def test_13_el_costo_no_aparece_como_medida_del_pivot(self):
        """El agujero real que la capa de presentación no tapaba."""
        campos = self.as_branch_user('stock.quant.product.location.report').fields_get()
        for campo in ('value_report',):
            self.assertNotIn(
                campo, campos,
                'El campo %s sigue disponible: el usuario puede agregarlo como medida '
                'desde el desplegable del pivot.' % campo)
        # Las columnas de disponibilidad sí tienen que estar.
        for campo in ('quantity', 'reserved_quantity', 'available_quantity',
                      'product_id', 'location_id'):
            self.assertIn(campo, campos)

    def test_13b_el_costo_de_gestion_tambien(self):
        """Solo aplica si el módulo puente está instalado."""
        modelo = self.env['stock.quant.product.location.report']
        if 'management_cost' not in modelo._fields:
            self.skipTest('primate_management_cost no está instalado.')
        campos = self.as_branch_user('stock.quant.product.location.report').fields_get()
        for campo in ('management_cost', 'management_value', 'management_rate'):
            self.assertNotIn(campo, campos)

    def test_14_la_accion_del_perfil_no_tiene_columnas_de_costo(self):
        vista = self.env.ref('forum_branch_security.view_stock_query_branch_tree')
        for campo in ('value_report', 'management_cost', 'management_value'):
            self.assertNotIn('name="%s"' % campo, vista.arch)
        accion = self.env.ref('forum_branch_security.action_stock_query_branch')
        self.assertEqual(accion.view_mode, 'tree')

    def test_15_el_grupo_de_costo_no_lo_implica_nadie(self):
        """Si lo implicara base.group_user lo tendría todo el mundo y no serviría."""
        implican = self.env['res.groups'].search([
            ('implied_ids', 'in', self.cost_group.id)])
        self.assertFalse(
            implican,
            'El grupo de costo lo implica %s: entonces el perfil sucursal también lo '
            'tiene y el mecanismo no sirve.' % implican.mapped('name'))
