# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import BranchProfileCase


@tagged('post_install', '-at_install')
class TestBranchProfile(BranchProfileCase):

    def test_01_ve_solo_su_almacen(self):
        visibles = self.as_branch_user('stock.warehouse').search([])
        self.assertIn(self.warehouse, visibles)
        self.assertNotIn(self.otro_warehouse, visibles)
        # Lo unico que se suma al propio es el almacen de un tipo de operacion
        # que el perfil ya le deja ver: en franquicia, el del PdV. Ver test_15.
        tipos_visibles = self.as_branch_user('stock.picking.type').search([])
        self.assertFalse(visibles - (self.warehouse | tipos_visibles.warehouse_id))

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

    def test_13_si_ve_el_tipo_de_operacion_puede_ejecutarlo(self):
        """Las ubicaciones del tipo de operación visible son legibles.

        El criterio es: si el perfil deja ver un tipo de operación, tiene que
        dejar ejecutarlo. El destino configurado en el tipo le llega al usuario
        como valor por defecto —el desplegable ya está filtrado, así que no lo
        elige— y si no puede leerlo el formulario falla recién al guardar.
        """
        destino_ajeno = self.otro_warehouse.lot_stock_id
        sub_ajena = self.env['stock.location'].create({
            'name': 'Sub BP', 'location_id': destino_ajeno.id, 'usage': 'internal',
            'company_id': self.otro_warehouse.company_id.id,
        })
        nunca_usada = self.otro_warehouse.view_location_id

        # Sin ningún tipo visible que la use, la ubicación ajena está cerrada.
        self.env.registry.clear_cache()
        with self.assertRaises(AccessError):
            destino_ajeno.with_user(self.user).read(['complete_name'])

        tipo = self.env['stock.picking.type'].create({
            'name': 'Intercambio BP', 'code': 'outgoing', 'sequence_code': 'IBP',
            'warehouse_id': self.warehouse.id,
            'company_id': self.warehouse.company_id.id,
            'default_location_src_id': self.warehouse.lot_stock_id.id,
            'default_location_dest_id': destino_ajeno.id,
        })
        # _compute_domain está cacheado: el permiso nuevo no aparece hasta limpiar.
        self.env.registry.clear_cache()

        self.assertIn(tipo, self.as_branch_user('stock.picking.type').search([]))
        destino_ajeno.with_user(self.user).read(['complete_name'])
        sub_ajena.with_user(self.user).read(['complete_name'])

        picking = self.as_branch_user('stock.picking').create({
            'picking_type_id': tipo.id,
            'location_id': self.warehouse.lot_stock_id.id,
            'location_dest_id': destino_ajeno.id,
        })
        self.assertTrue(picking)

        # La vista del otro almacén no la usa ningún tipo visible: sigue cerrada.
        with self.assertRaises(AccessError):
            nunca_usada.with_user(self.user).read(['complete_name'])

    def test_14_el_destino_que_pone_el_contacto_tambien_se_abre(self):
        """Si el tipo no trae destino, lo pone el contacto — y también hay que leerlo.

        Es el caso real del intercambio entre sucursales: `Intercambio - Envio`
        no tiene destino configurado, así que `stock.picking._compute_location_id`
        cae en `partner_id.property_stock_customer`, que apunta a la ubicación de
        salida de la sucursal de destino. Mirar sólo los defaults del tipo de
        operación no alcanza.
        """
        tipo = self.warehouse.out_type_id
        self.assertFalse(
            tipo.default_location_dest_id,
            'La premisa del caso es un tipo de salida sin destino configurado.')

        salida_ajena = self.env['stock.location'].create({
            'name': 'Salida OBP', 'usage': 'internal',
            'location_id': self.otro_warehouse.view_location_id.id,
            'company_id': self.otro_warehouse.company_id.id,
        })
        contacto = self.env['res.partner'].create({'name': 'Sucursal OBP'})

        # Sin la propiedad, la ubicación de salida ajena está cerrada.
        self.env.registry.clear_cache()
        with self.assertRaises(AccessError):
            salida_ajena.with_user(self.user).read(['complete_name'])

        contacto.with_company(
            self.otro_warehouse.company_id).property_stock_customer = salida_ajena
        self.env.registry.clear_cache()

        salida_ajena.with_user(self.user).read(['complete_name'])
        picking = self.as_branch_user('stock.picking').create({
            'picking_type_id': tipo.id,
            'partner_id': contacto.id,
        })
        self.assertEqual(picking.location_dest_id, salida_ajena)

    def test_15_el_almacen_del_pdv_es_legible(self):
        """En franquicia el PdV mueve stock en otro almacen, y hay que leerlo.

        El `display_name` de un tipo de operacion es `<almacen>: <nombre>`, asi
        que un tipo visible con el almacen cerrado rompe el `web_search_read`
        con el que el cliente web abre el tablero de Inventario: la pantalla no
        carga y salta un AccessError sobre `stock.warehouse`.
        """
        almacen_pdv = self.env['stock.warehouse'].create({
            'name': 'Almacen PdV BP', 'code': 'APDV',
            'company_id': self.franquicia.id,
        })
        self.pos_config.picking_type_id = almacen_pdv.out_type_id
        self.assertNotIn(almacen_pdv, self.user.branch_warehouse_ids)
        self.env.registry.clear_cache()

        visibles = self.as_branch_user('stock.picking.type').search([])
        self.assertIn(almacen_pdv.out_type_id, visibles)

        # Esto es lo que falla si el almacen del PdV no se abre.
        visibles.with_user(self.user).read(['display_name'])
        almacen_pdv.with_user(self.user).read(['name'])

        # Y el almacen de la otra sucursal sigue cerrado.
        self.assertNotIn(
            self.otro_warehouse, self.as_branch_user('stock.warehouse').search([]))


    def _arma_el_intercambio(self):
        """El circuito de intercambio entre sucursales, con sus tres tramos.

        Lo arma como en FORUM: el usuario que envía es de la casa central —su
        compañía activa es la de las ubicaciones, que es lo que hace que
        `_push_apply` tome la rama **sin** sudo del core— y los dos tramos que
        siguen son reglas push de una ruta del almacén que envía.
        """
        self.salida = self.env['stock.location'].create({
            'name': 'Salida Otro BP', 'usage': 'internal',
            'location_id': self.otro_warehouse.view_location_id.id,
            'company_id': self.casa_central.id,
        })
        self.transito = self.env['stock.location'].create({
            'name': 'Transito Otro BP', 'usage': 'transit',
            'company_id': self.casa_central.id,
        })
        self.destino_final = self.otro_warehouse.lot_stock_id

        # El envío le llega con la salida del destino ya puesta, que es lo que
        # abrió _branch_operation_location_ids.
        self.tipo_envio = self.warehouse.out_type_id
        self.tipo_envio.default_location_dest_id = self.salida

        ruta = self.env['stock.route'].create({
            'name': 'Puente BP', 'warehouse_selectable': True,
            'company_id': self.casa_central.id,
            'warehouse_ids': [(6, 0, [self.warehouse.id])],
        })
        self.env['stock.rule'].create({
            'name': 'Puente BP: salida -> transito', 'route_id': ruta.id,
            'action': 'push', 'auto': 'transparent',
            'location_src_id': self.salida.id, 'location_dest_id': self.transito.id,
            'picking_type_id': self.otro_warehouse.int_type_id.id,
            'company_id': self.casa_central.id,
        })
        self.env['stock.rule'].create({
            'name': 'Puente BP: transito -> existencias', 'route_id': ruta.id,
            'action': 'push', 'auto': 'manual',
            'location_src_id': self.transito.id,
            'location_dest_id': self.destino_final.id,
            'picking_type_id': self.otro_warehouse.in_type_id.id,
            'company_id': self.casa_central.id,
        })

        self.producto = self.env['product.product'].create({
            'name': 'Producto Puente BP', 'type': 'product',
        })
        self.env['stock.quant']._update_available_quantity(
            self.producto, self.warehouse.lot_stock_id, 5)

        # Un usuario de sucursal de la casa central, como los "Usuario - Suc. X"
        # de FORUM: el del fixture es de franquicia y opera en otra compañía.
        self.usuario_central = self.env['res.users'].create({
            'name': 'Cajero Central BP', 'login': 'cajero.central.bp',
            'company_id': self.casa_central.id,
            'company_ids': [(6, 0, [self.casa_central.id])],
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.branch_group.id,
            ])],
        })
        self.usuario_central.branch_warehouse_ids = self.warehouse

        # _compute_domain está cacheado y el destino del tipo acaba de cambiar.
        self.env.registry.clear_cache()

    def _envia_a_la_otra_sucursal(self):
        """Crea, confirma y valida el envío como el usuario de sucursal."""
        picking = self.env['stock.picking'].with_user(self.usuario_central).create({
            'picking_type_id': self.tipo_envio.id,
            'location_id': self.warehouse.lot_stock_id.id,
            'location_dest_id': self.salida.id,
        })
        self.env['stock.move'].with_user(self.usuario_central).create({
            'name': 'Puente BP', 'picking_id': picking.id,
            'product_id': self.producto.id, 'product_uom_qty': 1,
            'location_id': self.warehouse.lot_stock_id.id,
            'location_dest_id': self.salida.id,
        })
        picking.action_confirm()
        picking.action_assign()
        picking.move_ids.write({'quantity': 1, 'picked': True})
        picking.button_validate()
        return picking

    def test_16_el_tramo_puente_lo_ejecuta_el_codigo(self):
        """El envío se confirma y se valida aunque la cadena siga en otro local.

        El intercambio son tres tramos y el operador sólo conoce el primero. Los
        otros dos los aplica `_push_apply` dentro de su propio `_action_confirm`,
        y el último termina en la ubicación de existencias de la otra sucursal:
        `internal` y de otro almacén, o sea justo lo que el perfil oculta. El
        usuario no la elige ni la ve, se la pone la regla.
        """
        self._arma_el_intercambio()

        picking = self._envia_a_la_otra_sucursal()

        self.assertEqual(picking.state, 'done')
        move = self.env['stock.move'].browse(picking.move_ids.ids)
        self.assertEqual(
            move.location_dest_id, self.transito,
            'El tramo transparente tiene que haber corrido el destino a tránsito.')
        recepcion = move.move_dest_ids
        self.assertTrue(recepcion, 'Falta el tramo que recibe en la otra sucursal.')
        self.assertEqual(recepcion.location_dest_id, self.destino_final)
        self.assertEqual(
            recepcion.picking_id.picking_type_id, self.otro_warehouse.in_type_id)

    def test_16b_el_tramo_puente_no_se_le_muestra_a_quien_envia(self):
        """Lo que se eleva es la ejecución del tramo, no lo que el perfil deja ver."""
        self._arma_el_intercambio()
        picking = self._envia_a_la_otra_sucursal()
        recepcion = self.env['stock.move'].browse(picking.move_ids.ids).move_dest_ids

        como_usuario = lambda modelo: self.env[modelo].with_user(self.usuario_central)
        self.assertNotIn(recepcion.picking_id, como_usuario('stock.picking').search([]))
        self.assertNotIn(recepcion, como_usuario('stock.move').search([]))
        self.assertNotIn(
            self.otro_warehouse, como_usuario('stock.warehouse').search([]))
        with self.assertRaises(AccessError):
            self.destino_final.with_user(self.usuario_central).read(['complete_name'])
