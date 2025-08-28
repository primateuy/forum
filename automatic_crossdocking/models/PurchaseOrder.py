from odoo import fields, api, models, SUPERUSER_ID
import logging
from odoo.exceptions import ValidationError
import math

_logger = logging.getLogger(__name__)

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'
    
    crossdock_enabled = fields.Boolean(
        string="Crossdock habilitado",
        default=False
    )

    crossdock_percentage = fields.Float(
        string="Porcentaje por defecto para las líneas",
        default=80.0
    )

    distribution_rounding_method = fields.Selection([
        ('nearest', 'Redondeo a múltiplo más cercano'),
        ('floor', 'Redondeo a múltiplo inferior'),
        ('ceil', 'Redondeo a múltiplo superior')
    ], default='nearest', string="Metódo de Redondeo");

    crossdock_lines_count = fields.Integer(
        string='Líneas Crossdock',
        compute='_compute_crossdock_lines_count'
    )



    def llamarComponente(self):
        distributions = {}
        datosRenderizados = []
        crossdock_orders = self.filtered(lambda po: po.crossdock_enabled)
        
        for order in crossdock_orders:
            
            if order.state not in ('purchase', 'done'):
                continue
            
            if not any(line.product_id.type in ['product', 'consu'] for line in order.order_line):

                continue
            
            order = order.with_company(order.company_id)
            lineas_crossdock = order.order_line.filtered(lambda l: l.use_crossdock)
            
            if lineas_crossdock:
                if order._are_required_modules_installed():
                    order_dist = order._calculate_crossdock_distribution(lineas_crossdock)
                else:
                    almacenes = order.env['stock.warehouse'].search([
                        ('company_id', '=', order.company_id.id),
                        ('active', '=', True)
                    ])
                    order_dist = order._calculate_equitable_distribution(lineas_crossdock, almacenes)
                
                for location_or_warehouse, items in order_dist.items():
                    if location_or_warehouse in distributions:
                        distributions[location_or_warehouse].extend(items)
                    else:
                        distributions[location_or_warehouse] = items

        for destination, distribution_list in distributions.items():
            for dist_item in distribution_list:
                try:
                    line = dist_item['line']
                    quantity = dist_item['quantity']
                    warehouse = dist_item['warehouse'];

                    related_picking = self._find_related_picking(destination);
                    
                    related_move = self._find_related_move(line, destination, related_picking)

                    datosRenderizados.append({
                        'picking_id': related_picking.id if related_picking else None,
                        'picking_name': related_picking.name if related_picking else '',
                        'product_id': line.product_id.id,
                        'product_name': line.product_id.name,
                        'product_default_code': line.product_id.default_code or '',
                        'move_id': related_move.id if related_move else None,
                        'quantity': quantity,
                        'crossdock': line.line_crossdock_percentage,
                        'uom': line.product_uom.name,
                        'source_warehouse_id': warehouse.id,
                        'source_warehouse_name': warehouse.name,
                        'destination_location_id': destination.id if hasattr(destination, 'id') else warehouse.lot_stock_id.id,
                        'destination_location_name': destination.complete_name if hasattr(destination, 'complete_name') else warehouse.display_name,
                        'purchase_order_id': line.order_id.id,
                        'purchase_order_name': line.order_id.name,
                        'purchase_line_id': line.id
                    })
                    
                except Exception as e:
                    continue

       
        return {
            'name': 'Distribución Crossdock',
            'type': 'ir.actions.client',
            'tag': 'crossdock_distribution_template',
            'target': 'new',
            'context': datosRenderizados,
            'params': {
                'title': 'Distribución Cross-Docking',
                'message': '',
                'type': 'info',
                'sticky': True,
            }
        }


    def _find_related_move(self, purchase_line, destination_location, picking=None):
        domain = [
            ('purchase_line_id', '=', purchase_line.id),
            ('location_dest_id', '=', destination_location.id),
            ('state', 'not in', ['done', 'cancel']),
        ]
        
        if picking:
            domain.append(('picking_id', '=', picking.id))
        
        move = self.env['stock.move'].search(domain, limit=1)
        return move    
    
        

    def _find_related_picking(self, destination_location):
        
        domain = [
            ('origin', 'like', self.name),
            ('state', 'not in', ['done', 'cancel']),
            ('location_dest_id', '=', destination_location.id),
        ]
        
        if hasattr(destination_location, 'complete_name') and 'Crossdock' in str(self.name):
            domain.append(('origin', 'ilike', 'crossdock'))
        
        picking = self.env['stock.picking'].search(domain, limit=1)
        return picking



    @api.depends('order_line.use_crossdock')
    def _compute_crossdock_lines_count(self):
        """Contar líneas con crossdocking habilitado"""
        for record in self:
            record.crossdock_lines_count = len(record.order_line.filtered('use_crossdock'))

    
    
    
    def _create_crossdock_picking(self, order_line, distributions):
        
        source_location = self.picking_type_id.default_location_dest_id;
        warehouse_groups = {}
        for dist in distributions:
            warehouse_id = dist['warehouse'].id
            if warehouse_id not in warehouse_groups:
                warehouse_groups[warehouse_id] = {
                    'warehouse': dist['warehouse'],
                    'total_quantity': 0,
                    'is_principal': dist['is_principal']
                }
            warehouse_groups[warehouse_id]['total_quantity'] += dist['quantity']
        
        for warehouse_id, group in warehouse_groups.items():
            if group['total_quantity'] <= 0:
                continue
                
            warehouse = group['warehouse']
            
            picking_vals = {
                'picking_type_id': self._get_crossdock_picking_type(warehouse).id,
                'partner_id': self.partner_id.id,
                'origin': f"Crossdock {self.name}",
                'location_id': source_location.id,
                'location_dest_id': warehouse.lot_stock_id.id,
                'state': 'draft',
                'move_type': 'direct',
                
            }
            
            picking = self.env['stock.picking'].create(picking_vals)
            
            move_vals = {
                'name': f"Crossdock: {order_line.product_id.display_name}",
                'product_id': order_line.product_id.id,
                'product_uom_qty': group['total_quantity'],
                'product_uom': order_line.product_uom.id,
                'picking_id': picking.id,
                'location_id': source_location.id,
                'location_dest_id': warehouse.lot_stock_id.id,
                'origin': f"PO {self.name}",
                'state': 'draft',
                'warehouse_id': warehouse.id,
            }
            
            move = self.env['stock.move'].create(move_vals)
            
            try:
                picking.action_confirm()
                picking.action_assign()
                
                if hasattr(self, 'auto_validate_crossdock') and self.auto_validate_crossdock:
                    for move_line in picking.move_line_ids:
                        move_line.qty_done = move_line.product_uom_qty
                    
                    picking.button_validate();
                    
            except Exception as e:
                
                self.message_post(
                    body=f"⚠️ Error en crossdocking para {order_line.product_id.display_name}: {str(e)}"
                )

    def _get_crossdock_picking_type(self, target_warehouse):
        crossdock_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('warehouse_id', '=', self.picking_type_id.warehouse_id.id),
            ('name', 'ilike', 'crossdock')
        ], limit=1);

        
        if not crossdock_type:
            crossdock_type = self.env['stock.picking.type'].create({
                'name': 'Crossdocking',
                'code': 'internal',
                'sequence_code': 'CROSS',
                'warehouse_id': self.picking_type_id.warehouse_id.id,
                'default_location_src_id': self.picking_type_id.default_location_dest_id.id ,
                'default_location_dest_id': target_warehouse.id,
                'use_create_lots': False,
                'use_existing_lots': True,
            })
        
        return crossdock_type


    def redondeo(self, val, multiplo=1):
        if multiplo <= 0:
            multiplo = 1
        
        if self.distribution_rounding_method == 'nearest':
            return round(val / multiplo) * multiplo
        elif self.distribution_rounding_method == 'floor':
            return math.floor(val / multiplo) * multiplo
        else:
            return math.ceil(val / multiplo) * multiplo

    


    def button_confirm(self, *args, **kwargs):
        res = super(PurchaseOrder, self).button_confirm(*args, **kwargs)

        

        return res
    

  

    def _create_equitable_distribution_pickings(self, crossdock_lines):
        
        StockPicking = self.env['stock.picking']
        all_pickings = self.env['stock.picking']
        all_moves = self.env['stock.move']
        
        almacenes = self.env['stock.warehouse'].search([
            ('company_id', '=', self.company_id.id),
            ('active', '=', True)
        ])
        
        if len(almacenes) <= 1:
            return self._create_crossdocking_pickings_for_lines(crossdock_lines)
        
        # Calcular distribución equitativa (ahora retorna por ubicaciones)
        location_distribution = self._calculate_equitable_distribution(crossdock_lines, almacenes)
        
        if not location_distribution:
            return
        
        # Crear pickings para cada ubicación
        for location, lines_data in location_distribution.items():
            if not lines_data:
                continue

            # Obtener el almacén correspondiente a esta ubicación
            warehouse = None
            for almacen in almacenes:
                if location.id in almacen.view_location_id.with_context(active_test=False).search([
                    ('id', 'child_of', almacen.view_location_id.id)
                ]).ids:
                    warehouse = almacen
                    break
            
            if not warehouse:
                continue

            existing_picking = self.picking_ids.filtered(
                lambda p: p.location_dest_id.id == location.id and 
                p.state not in ('done', 'cancel') and
                'Crossdock' in (p.origin or '')
            )
            
            if existing_picking:
                picking = existing_picking[0]
                
            else:
                picking_vals = self._prepare_picking()
                picking_vals.update({
                    'location_dest_id': location.id,  # Usar la ubicación específica
                    'origin': f"{self.name} - Crossdock Equitativo {location.complete_name}",
                    'picking_type_id': self._get_crossdock_picking_type(warehouse).id
                })
                
                picking = StockPicking.with_user(SUPERUSER_ID).create(picking_vals)
            
            all_pickings |= picking
            
            # Usar el método existente para crear movimientos
            picking_moves = self._create_equitable_moves_for_picking(picking, location, lines_data)
            all_moves |= picking_moves
            
            picking.message_post_with_source(
                'mail.message_origin_link',
                render_values={'self': picking, 'origin': self},
                subtype_xmlid='mail.mt_note',
            )
        
        if all_moves:
            all_moves = all_moves.filtered(lambda x: x.state not in ('done', 'cancel'))._action_confirm()
            
            seq = 0
            for move in sorted(all_moves, key=lambda move: move.date):
                seq += 5
                move.sequence = seq
            
            all_moves._action_assign()
            
            forward_pickings = self.env['stock.picking']._get_impacted_pickings(all_moves)
            (all_pickings | forward_pickings).action_confirm()

    def _create_equitable_moves_for_picking(self, picking, location, lines_data):
        """Crear movimientos para picking con distribución equitativa por ubicación"""
        
        moves = self.env['stock.move']
        
        for line_data in lines_data:
            line = line_data['line']
            quantity = line_data['quantity']
            warehouse = line_data['warehouse']
            is_equitable = line_data.get('is_equitable', False)
            is_principal = line_data.get('is_principal', False)
            
            if quantity <= 0:
                continue

            # Nombre descriptivo del movimiento
            if is_principal:
                move_name = f"Principal: {line.product_id.display_name} → {location.complete_name}"
            elif is_equitable:
                move_name = f"Equitativo: {line.product_id.display_name} → {location.complete_name}"
            else:
                move_name = f"Crossdock: {line.product_id.display_name} → {location.complete_name}"

            move_vals = {
                'name': move_name,
                'product_id': line.product_id.id,
                'product_uom_qty': quantity,
                'product_uom': line.product_uom.id,
                'location_id': self.partner_id.property_stock_supplier.id,
                'location_dest_id': location.id,  # Usar la ubicación específica
                'picking_id': picking.id,
                'partner_id': self.partner_id.id,
                'origin': self.name,
                'state': 'draft',
                'company_id': self.company_id.id,
                'purchase_line_id': line.id,
                'group_id': self.group_id.id,
                'price_unit': line.price_unit,
                'date': line.date_planned or self.date_planned or fields.Datetime.now(),
                'date_deadline': line.date_planned,
                'procure_method': 'make_to_stock',
                'warehouse_id': warehouse.id,
            }

            move = self.env['stock.move'].create(move_vals)
            moves |= move

        return moves
    
    def _calculate_equitable_distribution(self, crossdock_lines, almacenes):
        ubicaciones_disponibles = []
        
        for almacen in almacenes:
            if self._are_required_modules_installed():
                ubicaciones_internas = self.env['stock.location'].search([
                    ('usage', '=', 'internal'),
                    ('id', 'child_of', almacen.view_location_id.id),
                    ('replenish_location', '=', True),
                    ('automate_reordering', '=', True)
                ])
            else:
                ubicaciones_internas = self.env['stock.location'].search([
                    ('usage', '=', 'internal'),
                    ('id', 'child_of', almacen.view_location_id.id),
                    ('replenish_location', '=', True),
                ])
            
            for ubicacion in ubicaciones_internas:
                ubicaciones_disponibles.append((ubicacion, almacen))
        
        distribution = {}
        for ubicacion, almacen in ubicaciones_disponibles:
            distribution[ubicacion] = []
        
        num_ubicaciones = len(ubicaciones_disponibles)
        
        if num_ubicaciones == 0:
            return {}
        
        ubicacion_principal = self.picking_type_id.default_location_dest_id
        
        if num_ubicaciones == 1:
            ubicacion_unica, almacen_unico = ubicaciones_disponibles[0]
            
            for line in crossdock_lines:
                cantidad_total = line.product_qty
                
                if cantidad_total > 0:
                    is_principal = (ubicacion_unica == ubicacion_principal)
                    
                    distribution[ubicacion_unica].append({
                        'line': line,
                        'quantity': cantidad_total,
                        'warehouse': almacen_unico,
                        'is_equitable': False,  # No es distribución equitativa
                        'is_principal': is_principal,
                        'is_single_location': True  # Marcador para identificar este caso
                    })
                    
            
            return {k: v for k, v in distribution.items() if v}
        
        # LÓGICA ORIGINAL para múltiples ubicaciones
        for line in crossdock_lines:
            porcentaje = line.line_crossdock_percentage or (self.crossdock_percentage / 100)
            
            if porcentaje <= 0:
                continue

            cantidad_total = line.product_qty
            
            # Cantidad para distribuir equitativamente (porcentaje especificado)
            cantidad_para_distribuir = self.redondeo(cantidad_total * porcentaje, line.distribution_multiple)
            cantidad_para_principal = self.redondeo(cantidad_total - cantidad_para_distribuir, line.distribution_multiple)
            
            ubicacion_principal_disponible = any(ub == ubicacion_principal for ub, _ in ubicaciones_disponibles)
            
            # CASO ESPECIAL: Si solo hay ubicación principal disponible
            if ubicacion_principal_disponible and num_ubicaciones == 1:
                
                almacen_principal = next(alm for ub, alm in ubicaciones_disponibles if ub == ubicacion_principal)
                
                distribution[ubicacion_principal].append({
                    'line': line,
                    'quantity': cantidad_total,  # Todo va a principal
                    'warehouse': almacen_principal,
                    'is_equitable': False,
                    'is_principal': True,
                    'is_single_location': True
                })
                continue
            
            # Filtrar ubicaciones para distribución (excluyendo principal si está disponible)
            if ubicacion_principal_disponible:
                ubicaciones_para_distribuir = [(ub, alm) for ub, alm in ubicaciones_disponibles 
                                            if ub != ubicacion_principal]
            else:
                # Si la principal no está disponible, usar todas las ubicaciones para distribución
                ubicaciones_para_distribuir = ubicaciones_disponibles
                cantidad_para_principal = 0  # No hay principal, todo se distribuye
                cantidad_para_distribuir = cantidad_total
            
            num_ubicaciones_distribuir = len(ubicaciones_para_distribuir)
            
            # CASO ESPECIAL: Si después de filtrar solo queda una ubicación para distribuir
            if num_ubicaciones_distribuir == 1:
                ubicacion_unica, almacen_unico = ubicaciones_para_distribuir[0]
                
                distribution[ubicacion_unica].append({
                    'line': line,
                    'quantity': cantidad_para_distribuir,  # Toda la cantidad de distribución
                    'warehouse': almacen_unico,
                    'is_equitable': False,  # No es equitativa porque es la única
                    'is_principal': False,
                    'is_single_distribution_location': True
                })
                
                
            elif num_ubicaciones_distribuir > 1:
                # Distribución equitativa normal entre múltiples ubicaciones
                cantidad_por_ubicacion = cantidad_para_distribuir / num_ubicaciones_distribuir
                cantidad_restante_distribuir = cantidad_para_distribuir
                
                for i, (ubicacion, almacen) in enumerate(ubicaciones_para_distribuir):
                    if i == num_ubicaciones_distribuir - 1:
                        # Última ubicación recibe el restante para evitar problemas de redondeo
                        cantidad_asignada = cantidad_restante_distribuir
                    else:
                        cantidad_asignada = self.redondeo(cantidad_por_ubicacion)
                        cantidad_restante_distribuir -= cantidad_asignada
                    
                    if cantidad_asignada > 0:
                        distribution[ubicacion].append({
                            'line': line,
                            'quantity': cantidad_asignada,
                            'warehouse': almacen,
                            'is_equitable': True,
                            'is_principal': False
                        })
                        
            
            # Asignar cantidad restante a la ubicación principal (si existe y está disponible)
            if cantidad_para_principal > 0 and ubicacion_principal and ubicacion_principal_disponible:
                almacen_principal = next(alm for ub, alm in ubicaciones_disponibles if ub == ubicacion_principal)
                
                distribution[ubicacion_principal].append({
                    'line': line,
                    'quantity': cantidad_para_principal,
                    'warehouse': almacen_principal,
                    'is_equitable': False,
                    'is_principal': True
                })
                
        
        # Filtrar ubicaciones sin asignaciones
        filtered_distribution = {k: v for k, v in distribution.items() if v}
        
        
        return filtered_distribution
    
    def _are_required_modules_installed(self):
            required_modules = [
                'automatizacion_reglas_abastecimiento',  
                'setu_advance_reordering'   
            ]
            
            installed_modules = self.env['ir.module.module'].search([
                ('name', 'in', required_modules),
                ('state', '=', 'installed')
            ])
            
            installed_names = installed_modules.mapped('name')
            missing_modules = [mod for mod in required_modules if mod not in installed_names]
            
            if missing_modules:
                return False
            
            return True

    def _create_picking(self):
        
        regular_orders = self.filtered(lambda po: not po.crossdock_enabled)
        crossdock_orders = self.filtered(lambda po: po.crossdock_enabled)
        
        if regular_orders:
            super(PurchaseOrder, regular_orders)._create_picking() 

        for order in crossdock_orders:
            if order.state not in ('purchase', 'done'):
                continue
            
            if not any(product.type in ['product', 'consu'] for product in order.order_line.product_id):
                continue
            
            order = order.with_company(order.company_id)
            
            lineas_regulares = order.order_line.filtered(lambda l: not l.use_crossdock) 
            lineas_crossdock = order.order_line.filtered(lambda l: l.use_crossdock) 
            
            
            if lineas_regulares:
                order._create_regular_picking_for_lines(lineas_regulares)
            
            if lineas_crossdock:
                if order._are_required_modules_installed():
                    order._create_crossdocking_pickings_for_lines(lineas_crossdock)
                else:
                    order._create_equitable_distribution_pickings(lineas_crossdock)
        
        return True

    def _create_regular_picking_for_lines(self, regular_lines):
       
        StockPicking = self.env['stock.picking']
        
        existing_picking = self.picking_ids.filtered(
            lambda p: p.state not in ('done', 'cancel') and 
            'Crossdock' not in (p.origin or '')
        )
        
        if existing_picking:
            picking = existing_picking[0]
        else:
            picking_vals = self._prepare_picking()
            picking = StockPicking.with_user(SUPERUSER_ID).create(picking_vals)

        
        moves = regular_lines._create_stock_moves(picking)
        moves = moves.filtered(lambda x: x.state not in ('done', 'cancel'))._action_confirm()
        
        seq = 0
        for move in sorted(moves, key=lambda move: move.date):
            seq += 5
            move.sequence = seq
        
        moves._action_assign()
        forward_pickings = self.env['stock.picking']._get_impacted_pickings(moves)
        (picking | forward_pickings).action_confirm()
        
        picking.message_post_with_source(
            'mail.message_origin_link',
            render_values={'self': picking, 'origin': self},
            subtype_xmlid='mail.mt_note',
        )

    def _create_crossdocking_pickings_for_lines(self, crossdock_lines):
        
        StockPicking = self.env['stock.picking']
        all_pickings = self.env['stock.picking']
        all_moves = self.env['stock.move']
        
        warehouse_distribution = self._calculate_crossdock_distribution(crossdock_lines)
        
        if not warehouse_distribution:
            return
        
        for ubi, alm in warehouse_distribution.items():
            

            existing_picking = self.picking_ids.filtered(
                lambda p: p.location_dest_id.id == ubi.id and 
                p.state not in ('done', 'cancel') and
                'Crossdock' in (p.origin or '')
            )
            
            if existing_picking:
                picking = existing_picking[0]
            else:
                picking_vals = self._prepare_picking()
                picking_vals.update({
                    'location_dest_id': ubi.id,
                    'origin': f"{self.name} - Crossdock {ubi.display_name}",
                    'picking_type_id': self._get_crossdock_picking_type(ubi).id
                })
                
                picking = StockPicking.with_user(SUPERUSER_ID).create(picking_vals)
            
            all_pickings |= picking
            
            picking_moves = self._create_crossdock_moves_for_picking(picking, ubi, alm)
            all_moves |= picking_moves
            
            picking.message_post_with_source(
                'mail.message_origin_link',
                render_values={'self': picking, 'origin': self},
                subtype_xmlid='mail.mt_note',
            )
        
        if all_moves:
            all_moves = all_moves.filtered(lambda x: x.state not in ('done', 'cancel'))._action_confirm()
            
            seq = 0
            for move in sorted(all_moves, key=lambda move: move.date):
                seq += 5
                move.sequence = seq
            
            all_moves._action_assign()
            
            forward_pickings = self.env['stock.picking']._get_impacted_pickings(all_moves)
            (all_pickings | forward_pickings).action_confirm()
        

    def _calculate_crossdock_distribution(self, crossdock_lines):
        distribution = {}
        almacenes = self.env['stock.warehouse'].search([
            ('company_id', '=', self.company_id.id),
            ('active', '=', True)
        ])

        ubicaciones_lot_stock = []
        ubicacion_principal = self.picking_type_id.default_location_dest_id
        
        for almacen in almacenes:
            ubicaciones_internas = None

            if self._are_required_modules_installed():
                ubicaciones_internas = self.env['stock.location'].search([
                    ('usage', '=', 'internal'),
                    ('id', 'child_of', almacen.view_location_id.id),
                    ('replenish_location', '=', True),
                    ('automate_reordering', '=', True)
                ])
            else:
                ubicaciones_internas = self.env['stock.location'].search([
                    ('usage', '=', 'internal'),
                    ('id', 'child_of', almacen.view_location_id.id),
                    ('replenish_location', '=', True),
                ])
            
            for ubi in ubicaciones_internas:
                ubicaciones_lot_stock.append((ubi, almacen))
                distribution[ubi] = []

        if ubicacion_principal and ubicacion_principal not in distribution:
            # Buscar el almacén de la ubicación principal
            almacen_principal = None
            for almacen in almacenes:
                if ubicacion_principal.id in almacen.view_location_id.with_context(active_test=False).search([
                    ('id', 'child_of', almacen.view_location_id.id)
                ]).ids:
                    almacen_principal = almacen
                    break
            
            if almacen_principal:
                distribution[ubicacion_principal] = []
                # Agregar también a la lista si no está
                if (ubicacion_principal, almacen_principal) not in ubicaciones_lot_stock:
                    ubicaciones_lot_stock.append((ubicacion_principal, almacen_principal))
            

        for line in crossdock_lines:
            porcentaje = line.line_crossdock_percentage or (self.crossdock_percentage / 100)

            if porcentaje <= 0:
                continue

            cantidad_total = line.product_qty
            
            cantidad_crossdock_raw = cantidad_total * porcentaje
            cantidad_crossdock = self.redondeo(cantidad_crossdock_raw, line.distribution_multiple) 
            cantidad_principal = cantidad_total - cantidad_crossdock

            almacen_principal = None
            
            
            for ubi, alm in ubicaciones_lot_stock:
                if ubi == ubicacion_principal:
                    almacen_principal = alm
                    break

            cantidad_principal_final = cantidad_principal
            cantidad_restante = cantidad_crossdock

            
            for ubi, alm in ubicaciones_lot_stock:
                if ubi == ubicacion_principal:
                    continue

                if cantidad_restante <= 0:
                    break

                has_warehouse_groups = hasattr(alm, 'warehouse_group_ids') and alm.warehouse_group_ids
                has_location_limits = hasattr(ubi, 'default_max_qty') and hasattr(ubi, 'default_min_qty')

                if has_warehouse_groups and alm.warehouse_group_ids.category_rule_ids:
                    categoriasGrupo = alm.warehouse_group_ids.category_rule_ids
                    rule_found = False
                    
                    for cat in categoriasGrupo:
                        if cat.categ_id.id == line.product_id.categ_id.id:
                            if hasattr(cat, 'max_qty') and hasattr(cat, 'min_qty'):
                                cantidad_a_asignar = min(cantidad_restante, cat.max_qty)
                                if cantidad_a_asignar >= cat.min_qty:
                                    distribution[ubi].append({
                                        'line': line,
                                        'quantity': cantidad_a_asignar,
                                        'warehouse': alm
                                    })
                                    cantidad_restante -= cantidad_a_asignar
                                    rule_found = True
                                    break
                    
                    if not rule_found:
                        
                        num_locations = len([u for u, a in ubicaciones_lot_stock if u != ubicacion_principal])
                        if num_locations > 0:
                            cantidad_a_asignar = min(cantidad_restante, cantidad_restante // num_locations)
                            if cantidad_a_asignar > 0:
                                distribution[ubi].append({
                                    'line': line,
                                    'quantity': cantidad_a_asignar,
                                    'warehouse': alm
                                })
                                cantidad_restante -= cantidad_a_asignar

                elif has_location_limits and ubi.default_max_qty and ubi.default_min_qty:
                    
                    cantidad_a_asignar = min(cantidad_restante, ubi.default_max_qty)
                    if cantidad_a_asignar >= ubi.default_min_qty:
                        distribution[ubi].append({
                            'line': line,
                            'quantity': cantidad_a_asignar,
                            'warehouse': alm
                        })
                        cantidad_restante -= cantidad_a_asignar
                else:
                    
                    num_locations = len([u for u, a in ubicaciones_lot_stock if u != ubicacion_principal])
                    if num_locations > 0:
                        cantidad_a_asignar = cantidad_restante // num_locations
                        if cantidad_a_asignar > 0:
                            distribution[ubi].append({
                                'line': line,
                                'quantity': cantidad_a_asignar,
                                'warehouse': alm
                            })
                            cantidad_restante -= cantidad_a_asignar

            
            if ubicacion_principal and (cantidad_principal_final + cantidad_restante) > 0:
                # Verificar que la ubicación principal esté en el diccionario
                if ubicacion_principal in distribution:
                    if almacen_principal:
                        distribution[ubicacion_principal].append({
                            'line': line,
                            'quantity': cantidad_principal_final + cantidad_restante,
                            'warehouse': almacen_principal
                        })
                    

        
        

        return distribution

    def _create_crossdock_moves_for_picking(self, picking, location, lines_data):
        moves = self.env['stock.move']
        for line_data in lines_data:
            line = line_data['line']
            quantity = line_data['quantity']
            warehouse = line_data.get('warehouse')
            if quantity <= 0:
                continue

            move_vals = {
                'name': f"Crossdock: {line.product_id.display_name} → {location.display_name}",
                'product_id': line.product_id.id,
                'product_uom_qty': quantity,
                'product_uom': line.product_uom.id,
                'location_id': self.partner_id.property_stock_supplier.id,
                'location_dest_id': location.id,
                'picking_id': picking.id,
                'partner_id': self.partner_id.id,
                'origin': self.name,
                'state': 'draft',
                'company_id': self.company_id.id,
                'purchase_line_id': line.id,
                'group_id': self.group_id.id,
                'price_unit': line.price_unit,
                'date': line.date_planned or self.date_planned or fields.Datetime.now(),
                'date_deadline': line.date_planned,
                'procure_method': 'make_to_stock',
                'warehouse_id': warehouse.id if warehouse else False,
            }

            move = self.env['stock.move'].create(move_vals)
            moves |= move


        return moves

    def _apply_rounding(self, quantity, multiple):
        """Aplicar redondeo según método configurado"""
        
        if self.distribution_rounding_method == 'nearest':
            return round(quantity / multiple) * multiple
        elif self.distribution_rounding_method == 'floor':
            return math.floor(quantity / multiple) * multiple
        elif self.distribution_rounding_method == 'ceil':
            return math.ceil(quantity / multiple) * multiple
        
        return quantity