from odoo import fields, api, models, SUPERUSER_ID

from odoo.exceptions import ValidationError
import math

import logging;

_logger = logging.getLogger(__name__)


class PurchaseOrderType(models.Model):
    _inherit = 'purchase.order.type';
    
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


    def write(self, vals):
        res = super(PurchaseOrderType, self).write(vals)
        return res

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

    
    exceso = fields.Boolean(
        string="Hay exceso en la distribución",
        default=False
    )
    
    
    
    @api.onchange('order_type')
    def _onchange_order_type(self):
        res = super(PurchaseOrder, self)._onchange_order_type() if hasattr(super(PurchaseOrder, self), '_onchange_order_type') else {}
        
        if self.order_type and hasattr(self.order_type, 'crossdock_enabled'):
            
            self.crossdock_enabled = self.order_type.crossdock_enabled
            self.crossdock_percentage = self.order_type.crossdock_percentage
            self.distribution_rounding_method = self.order_type.distribution_rounding_method
            
            for line in self.order_line:
                line.use_crossdock = self.order_type.crossdock_enabled
                line.line_crossdock_percentage = self.order_type.crossdock_percentage / 100
                
                
        
        return res
    
    @api.onchange('crossdock_enabled', 'crossdock_percentage')
    def _onchange_crossdock_settings(self):
        if self.crossdock_enabled:
            for line in self.order_line:
                line.use_crossdock = True
                line.line_crossdock_percentage = self.crossdock_percentage / 100
        else:
            for line in self.order_line:
                line.use_crossdock = False


 
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

                    product_display_name = line.product_id.display_name
                    if hasattr(line.product_id, 'product_template_attribute_value_ids') and line.product_id.product_template_attribute_value_ids:
                        display_name = product_display_name
                    else:
                        display_name = line.product_id.product_tmpl_id.name

                    datosRenderizados.append({
                        'picking_id': related_picking.id if related_picking else None,
                        'picking_name': related_picking.name if related_picking else '',
                        'product_id': line.product_id.id,
                        'product_name': line.product_id.name,
                        'product_display': display_name,
                        'product_default_code': line.product_id.default_code or '',
                        'move_id': related_move.id if related_move else None,
                        'quantity': related_move.product_uom_qty,
                        'crossdock': line.line_crossdock_percentage,
                        'uom': line.product_uom.name,
                        'source_warehouse_id': warehouse.id,
                        'source_warehouse_name': warehouse.name,
                        'destination_location_id': destination.id if hasattr(destination, 'id') else warehouse.lot_stock_id.id,
                        'destination_location_name': destination.complete_name if hasattr(destination, 'complete_name') else warehouse.display_name,
                        'purchase_order_id': line.order_id.id,
                        'purchase_order_name': line.order_id.name,
                        'purchase_line_id': line.id,
                        'total_line_quantity': line.product_qty
                    })
                    
                except Exception as e:
                    self.message_post(
                        body=f"⚠️ Error en uno de los registros: {str(e)}"
                    )
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
            ('state', 'not in', ['cancel']),
        ]
        
        if picking:
            domain.append(('picking_id', '=', picking.id))
        
        move = self.env['stock.move'].search(domain, limit=1)
        return move    
    
        

    def _find_related_picking(self, destination_location):
        
        domain = [
            ('origin', 'like', self.name),
            ('state', 'not in', ['cancel']),
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


    


    def button_confirm(self, *args, **kwargs):
        res = super(PurchaseOrder, self).button_confirm(*args, **kwargs)


        if self.exceso:
            self.message_post(body=f"⚠️ La distribución ha generado un exceso. Se ajustó las cantidades para evitar errores en el inventario.")
            self.write({'exceso': False})

        return res
    

  

    
    def _create_equitable_distribution_pickings(self, crossdock_lines):
        """
        Crea pickings para distribución equitativa entre almacenes.
        Ahora sigue el mismo flujo completo de tres pasos:
        1. Recepción a WH/Entrada
        2. Distribución desde WH/Entrada a destinos
        3. Movimiento del saldo a WH/Existencias
        """

        StockPicking = self.env['stock.picking']
        all_pickings = self.env['stock.picking']
        all_moves = self.env['stock.move']
        
        almacenes = self.env['stock.warehouse'].search([
            ('company_id', '=', self.company_id.id),
            ('active', '=', True)
        ])
        
        if len(almacenes) <= 1:
            return self._create_crossdocking_pickings_for_lines(crossdock_lines)
        
        location_distribution = self._calculate_equitable_distribution(crossdock_lines, almacenes)
        
        if not location_distribution:
            return
        
        for location, lines_data in location_distribution.items():
            if not lines_data:
                continue

            warehouse = None
            for almacen in almacenes:
                if location.id in almacen.view_location_id.with_context(active_test=False).search([
                    ('id', 'child_of', almacen.view_location_id.id)
                ]).ids:
                    warehouse = almacen
                    break
            
            if not warehouse:
                continue

            esPrincipal = False;

            main_warehouse = self.picking_type_id.warehouse_id or self.env['stock.warehouse'].search([
            ('company_id', '=', self.company_id.id)
            ], limit=1)

            if main_warehouse.id == warehouse.id:
                esPrincipal = True;

            if not warehouse.crossdocking_type_id or not warehouse.crossdocking_location_id or not warehouse.crossdocking_reception_type_id:
                raise ValidationError("No se ha configurado correctamente el almacén %s para crossdocking. Por favor, revise la configuración." % warehouse.name)
            
            if not esPrincipal:
                if not main_warehouse.crossdocking_type_id or not main_warehouse.crossdocking_location_id or not main_warehouse.crossdocking_reception_type_id:
                    raise ValidationError("No se ha asignado operación para el crossdocking en el centro logístico")

                crossdockingPicking = self._prepare_picking();
                crossdockingPicking.update({
                    'location_dest_id': warehouse.crossdocking_location_id.id,
                    'location_id': self._get_or_create_entrance_location().id,
                    'origin': f"{self.name} - Crossdock Equitativo {location.complete_name}",
                    'picking_type_id': warehouse.crossdocking_type_id.id
                })


                crosspick = StockPicking.with_user(SUPERUSER_ID).create(crossdockingPicking);
                

                all_pickings |= crosspick;

                picking_moves = self._create_equitable_moves_for_picking(crosspick, location, lines_data);
                all_moves |= picking_moves;

           

            existing_picking = self.picking_ids.filtered(
                lambda p: p.location_dest_id.id == location.id and 
                p.state not in ('done', 'cancel') and
                'Crossdock' in (p.origin or '')
            )
            
            if existing_picking:
                picking = existing_picking[0]
                
            else:
                picking_vals = self._prepare_picking()

                if esPrincipal:
                    picking_vals.update({
                        'location_dest_id': location.id,
                        'location_id': self._get_or_create_entrance_location().id,
                        'origin': f"{self.name} - Crossdock Equitativo {location.complete_name}",
                        'picking_type_id': main_warehouse.crossdocking_type_id.id
                    })
                else:

                    picking_vals.update({
                        'location_dest_id': location.id,
                        'location_id': warehouse.crossdocking_location_id.id,
                        'origin': f"{self.name} - Crossdock Equitativo {location.complete_name}",
                        'picking_type_id': warehouse.crossdocking_reception_type_id.id
                    })
                
                picking = StockPicking.with_user(SUPERUSER_ID).create(picking_vals)
            
            all_pickings |= picking
            
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
            
            
            forward_pickings = self.env['stock.picking']._get_impacted_pickings(all_moves)
            (all_pickings | forward_pickings).action_confirm()
            
            # for picking in all_pickings:
            #     if picking.state != 'confirmed':
            #         try:
            #             picking.write({'state': 'waiting'});
            #         except:
            #             pass

            #         for move in all_moves:
            #             if move.move_line_ids:
            #                 move.move_line_ids.unlink()
            #             move.write({
            #                 'quantity': 0,
            #             })


            # #chequear pickings
            # _logger.info("===============================================");
            # for picking in all_pickings:
            #     _logger.info("Picking creado: %s - Estado: %s", picking.name, picking.state);

                        

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
                'quantity': 0,
                'product_uom': line.product_uom.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
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
        
        main_warehouse = self.picking_type_id.warehouse_id or self.env['stock.warehouse'].search([
            ('company_id', '=', self.company_id.id)
        ], limit=1)
        ubicacion_principal = main_warehouse.lot_stock_id if main_warehouse else self.picking_type_id.default_location_dest_id
        
        almacen_principal = None
        ubicacion_principal_disponible = False
        
        for ubi, alm in ubicaciones_disponibles:
            if ubi == ubicacion_principal:
                ubicacion_principal_disponible = True
                almacen_principal = alm
                break
        
        if not ubicacion_principal_disponible and ubicacion_principal:
            for almacen in almacenes:
                if ubicacion_principal.id in almacen.view_location_id.with_context(active_test=False).search([
                    ('id', 'child_of', almacen.view_location_id.id)
                ]).ids:
                    almacen_principal = almacen
                    break
            
            if not almacen_principal:
                almacen_principal = main_warehouse
            
            if almacen_principal:
                distribution[ubicacion_principal] = []
                ubicaciones_disponibles.append((ubicacion_principal, almacen_principal))
                ubicacion_principal_disponible = True
                num_ubicaciones += 1
        
        for line in crossdock_lines:
            porcentaje = line.line_crossdock_percentage or (self.crossdock_percentage / 100)
            
            operacion = almacen_principal.crossdocking_type_id;

            if operacion and operacion.respeta_multiplos:
                multiple = getattr(line, 'distribution_multiple', 1) or 1
                if multiple > 1 and line.product_qty % multiple != 0:
                    raise ValidationError("La operación respeta multiplos. La línea de orden de compra %s tiene una cantidad total (%s) que no es múltiplo de %s. Por favor, ajuste la cantidad o el múltiplo." % (line.name, line.product_qty, multiple))

            if porcentaje <= 0:
                continue

            cantidad_total = line.product_qty
            
            multiple = getattr(line, 'distribution_multiple', 1) or 1
            rounding_method = self.distribution_rounding_method or 'nearest'
            
            cantidad_para_distribuir = cantidad_total * porcentaje
            cantidad_para_principal = cantidad_total - cantidad_para_distribuir
            ubicaciones_para_distribuir = []
            for ubi, alm in ubicaciones_disponibles:
                if ubi != ubicacion_principal:
                    ubicaciones_para_distribuir.append((ubi, alm))
            
            num_ubicaciones_distribuir = len(ubicaciones_para_distribuir)
            
            if num_ubicaciones_distribuir == 0:
                # No hay ubicaciones para distribuir, todo va a la principal
                if ubicacion_principal_disponible:
                    cantidad_con_multiplo = self._apply_multiple_rounding(
                        cantidad_total, 
                        multiple, 
                        rounding_method
                    )
                    
                    distribution[ubicacion_principal].append({
                        'line': line,
                        'quantity': cantidad_con_multiplo,
                        'warehouse': almacen_principal,
                        'is_equitable': False,
                        'is_principal': True
                    })
            else:
                cantidad_por_ubicacion = cantidad_para_distribuir / num_ubicaciones_distribuir
                cantidad_restante_distribuir = cantidad_para_distribuir
                
                pending_distributions = []
                
                for i, (ubicacion, almacen) in enumerate(ubicaciones_para_distribuir):
                    if i == num_ubicaciones_distribuir - 1:
                        cantidad_calculada = cantidad_restante_distribuir
                    else:
                        cantidad_calculada = cantidad_por_ubicacion
                        cantidad_restante_distribuir -= cantidad_calculada
                    
                    if cantidad_calculada > 0:
                        pending_distributions.append({
                            'location': ubicacion,
                            'warehouse': almacen,
                            'quantity': cantidad_calculada
                        })
                
                if pending_distributions:
                    final_distributions, central_adjustment, warnings = self._apply_distribution_with_limit_control(
                        line, 
                        pending_distributions, 
                        cantidad_para_distribuir, 
                        rounding_method
                    )
                    
                    for warning in warnings:
                        self.message_post(body=warning)
                    
                    for dist in final_distributions:
                        distribution[dist['location']].append({
                            'line': line,
                            'quantity': dist['quantity'],
                            'warehouse': dist['warehouse'],
                            'is_equitable': True,
                            'is_principal': False
                        })
                    
                    # Ajustar cantidad principal con el ajuste central
                    cantidad_para_principal_ajustada = cantidad_para_principal + central_adjustment
                else:
                    cantidad_para_principal_ajustada = cantidad_para_principal
                
                # Asignar cantidad para la principal
                if ubicacion_principal_disponible and cantidad_para_principal_ajustada > 0:
                    cantidad_para_principal = cantidad_para_principal_ajustada
                    
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
            
            if lineas_crossdock:
                order._create_main_reception_picking(lineas_crossdock)
            
            # Crear picking regular para líneas sin crossdocking
            if lineas_regulares:
                order._create_regular_picking_for_lines(lineas_regulares)
            
            if lineas_crossdock:
                if order._are_required_modules_installed():
                    order._create_crossdocking_pickings_for_lines(lineas_crossdock)
                else:
                    order._create_equitable_distribution_pickings(lineas_crossdock)
                
                #order._create_balance_picking_to_stock(lineas_crossdock)
                
                # Establecer dependencias correctas entre pickings
                order._setup_picking_dependencies()
        
        return True

    def _setup_picking_dependencies(self):
        """
        Establece las dependencias correctas entre los pickings de crossdocking
        para que sigan el flujo estándar de Odoo
        """
        entrada_location = self._get_or_create_entrance_location()
        
        reception_picking = self.picking_ids.filtered(
            lambda p: p.location_dest_id.id == entrada_location.id and 
            'Recepción Crossdock' in (p.origin or '') and
            p.state not in ('done', 'cancel')
        )
        
        dependent_pickings = self.picking_ids.filtered(
            lambda p: p.location_id.id == entrada_location.id and 
            p.id != reception_picking.id and
            p.state not in ('done', 'cancel')
        )

        almacenes = self.env['stock.warehouse'].search([]);

        

        dependent_pickings_crossdocking = [];

        for almacen in almacenes:
            dependent_pickings_crossdocking.append(almacen.crossdocking_location_id.id);
        

        crossdocking_pickings_pendientes = self.picking_ids.filtered(
            lambda p: p.location_id.id in dependent_pickings_crossdocking and
            p.state not in ('done', 'cancel')
        )

        if reception_picking and dependent_pickings:
            reception_picking = reception_picking[0]

            
            for dependent_picking in dependent_pickings:
                dependent_picking.write({'state': 'waiting'});
                for reception_move in reception_picking.move_ids:
                    for dependent_move in dependent_picking.move_ids:
                        if reception_move.product_id.id == dependent_move.product_id.id:
                            # El movimiento dependiente debe esperar al movimiento de recepción
                            dependent_move.write({
                                'move_orig_ids': [(4, reception_move.id)]
                            })
                            reception_move.write({
                                'move_dest_ids': [(4, dependent_move.id)]
                            })

                            if dependent_move.move_line_ids:
                                dependent_move.move_line_ids.unlink()
                                dependent_move.write({
                                    'quantity': 0,
                                })
                
            dependent_pickings.action_confirm();

            for crossdock_picking in crossdocking_pickings_pendientes:
                crossdock_picking.write({'state': 'waiting'});
                for dependent_move in crossdock_picking.move_ids:
                    for dependent_picking in dependent_pickings:
                        for dep_move in dependent_picking.move_ids:
                            if dependent_move.product_id.id == dep_move.product_id.id:
                                # El movimiento dependiente debe esperar al movimiento de recepción
                                dep_move.write({
                                    'move_orig_ids': [(4, dependent_move.id)]
                                })
                                dependent_move.write({
                                    'move_dest_ids': [(4, dep_move.id)]
                                })

                                if dep_move.move_line_ids:
                                    dep_move.move_line_ids.unlink()
                                    dep_move.write({
                                        'quantity': 0,
                                    })

            crossdocking_pickings_pendientes.action_confirm();
            

        return True

    def get_crossdock_picking_states_summary(self):
        
        summary = {
            'reception': {},
            'crossdock': [],
            'balance': {},
            'regular': []
        }
        
        entrada_location = self._get_or_create_entrance_location()
        
        reception_picking = self.picking_ids.filtered(
            lambda p: p.location_dest_id.id == entrada_location.id and 
            'Recepción Crossdock' in (p.origin or '')
        )
        if reception_picking:
            reception_picking = reception_picking[0]
            summary['reception'] = {
                'name': reception_picking.name,
                'state': reception_picking.state,
                'state_description': dict(reception_picking._fields['state'].selection)[reception_picking.state]
            }
        
        crossdock_pickings = self.picking_ids.filtered(
            lambda p: p.location_id.id == entrada_location.id and 
            'Crossdock' in (p.origin or '') and 'Saldo' not in (p.origin or '')
        )
        for picking in crossdock_pickings:
            summary['crossdock'].append({
                'name': picking.name,
                'state': picking.state,
                'state_description': dict(picking._fields['state'].selection)[picking.state],
                'location_dest': picking.location_dest_id.complete_name
            })
        
        balance_picking = self.picking_ids.filtered(
            lambda p: p.location_id.id == entrada_location.id and 
            'Saldo' in (p.origin or '')
        )
        if balance_picking:
            balance_picking = balance_picking[0]
            summary['balance'] = {
                'name': balance_picking.name,
                'state': balance_picking.state,
                'state_description': dict(balance_picking._fields['state'].selection)[balance_picking.state]
            }
        
        # Pickings regulares (sin crossdocking)
        regular_pickings = self.picking_ids.filtered(
            lambda p: p.location_dest_id.id != entrada_location.id and 
            'Crossdock' not in (p.origin or '') and 'Saldo' not in (p.origin or '')
        )
        for picking in regular_pickings:
            summary['regular'].append({
                'name': picking.name,
                'state': picking.state,
                'state_description': dict(picking._fields['state'].selection)[picking.state]
            })
        
        return summary

    def action_activate_crossdock_pickings(self):
        """
        Acción manual para activar todos los pickings de crossdocking
        que estén en estado 'waiting' o 'confirmed'
        """
        if not self.crossdock_enabled:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Aviso',
                    'message': 'Esta orden no tiene crossdocking habilitado',
                    'type': 'warning',
                }
            }
        
        entrada_location = self._get_or_create_entrance_location()
        
        # Buscar pickings de crossdocking en estado waiting o confirmed
        crossdock_pickings = self.picking_ids.filtered(
            lambda p: (
                p.location_id.id == entrada_location.id and 
                p.state in ('waiting', 'confirmed') and
                ('Crossdock' in (p.origin or '') or 'Saldo' in (p.origin or ''))
            )
        )
        
        if not crossdock_pickings:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Información',
                    'message': 'No hay pickings de crossdocking para activar',
                    'type': 'info',
                }
            }
        
        activated_count = 0
        failed_activations = []
        
        for picking in crossdock_pickings:
            try:
                picking.action_assign()
                activated_count += 1
            except Exception as e:
                failed_activations.append(f"{picking.name}: {str(e)}")
        
        # Mensaje de resultado
        if activated_count > 0:
            message = f"{activated_count} pickings de crossdocking activados correctamente"
            if failed_activations:
                message += f"\n Fallos: {'; '.join(failed_activations)}"
            
            self.message_post(body=message)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Éxito',
                    'message': f'{activated_count} pickings activados',
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'No se pudo activar ningún picking',
                    'type': 'danger',
                }
            }

    def _get_crossdock_reception_picking_type(self):
        
        main_warehouse = self.picking_type_id.warehouse_id or self.env['stock.warehouse'].search([
            ('company_id', '=', self.company_id.id)
        ], limit=1)

        if main_warehouse and main_warehouse.crossdocking_reception_type_id:
            return main_warehouse.crossdocking_reception_type_id
        
        raise ValidationError("No se ha definido el tipo de picking de 'Recepción Crossdock' en el almacén principal.")


        # crossdock_reception_type = self.env['stock.picking.type'].search([
        #     ('code', '=', 'incoming'),
        #     ('warehouse_id', '=', main_warehouse.id),
        #     ('name', 'ilike', 'Recepción Crossdock')
        # ], limit=1)
        
        # if not crossdock_reception_type:
        #     standard_reception = self.env['stock.picking.type'].search([
        #         ('code', '=', 'incoming'),
        #         ('warehouse_id', '=', main_warehouse.id),
        #         ('default_location_dest_id', '!=', False)
        #     ], limit=1)
            
        #     crossdock_reception_type = self.env['stock.picking.type'].create({
        #         'name': 'Recepción Crossdock',
        #         'code': 'incoming',
        #         'sequence_code': 'IN-CROSS',
        #         'warehouse_id': main_warehouse.id,
        #         'default_location_src_id': self.partner_id.property_stock_supplier.id,
        #         'default_location_dest_id': self._get_or_create_entrance_location().id,
        #         'use_create_lots': standard_reception.use_create_lots if standard_reception else False,
        #         'use_existing_lots': standard_reception.use_existing_lots if standard_reception else True,
        #         'show_operations': True,
        #         'show_reserved': True,
        #         'sequence': 1,
        #     })
        
        # return crossdock_reception_type

    def _create_main_reception_picking(self, crossdock_lines):
        StockPicking = self.env['stock.picking']
        
        entrada_location = self._get_or_create_entrance_location()
        
        existing_picking = self.picking_ids.filtered(
            lambda p: p.location_dest_id.id == entrada_location.id and 
            p.state not in ('done', 'cancel') and
            'Recepción Crossdock' in (p.origin or '')
        )
        
        if existing_picking:
            picking = existing_picking[0]
        else:
            picking_vals = self._prepare_picking()
            picking_vals.update({
                'location_dest_id': entrada_location.id,
                'origin': f"{self.name} - Recepción Crossdock",
                'picking_type_id': self._get_crossdock_reception_picking_type().id
            })
            
            picking = StockPicking.with_user(SUPERUSER_ID).create(picking_vals)
        
        moves = self.env['stock.move']
        for line in crossdock_lines:
            if line.product_qty <= 0:
                continue
                
            move_vals = {
                'name': f"Recepción: {line.product_id.display_name} → {entrada_location.display_name}",
                'product_id': line.product_id.id,
                'product_uom_qty': line.product_qty,
                'product_uom': line.product_uom.id,
                'location_id': self.partner_id.property_stock_supplier.id,
                'location_dest_id': entrada_location.id,
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
                'quantity': line.product_qty,
                'warehouse_id': self.picking_type_id.warehouse_id.id,
                'propagate_cancel': False,
            }
            
            move = self.env['stock.move'].create(move_vals)
            moves |= move
        
        if moves:
            moves = moves.filtered(lambda x: x.state not in ('done', 'cancel'))
            
            for move in moves:
                move.write({'state': 'confirmed'})
            
            seq = 0
            for move in sorted(moves, key=lambda move: move.date):
                seq += 5
                move.sequence = seq
            
            
            picking.message_post_with_source(
                'mail.message_origin_link',
                render_values={'self': picking, 'origin': self},
                subtype_xmlid='mail.mt_note',
            )
            
            # Confirmar solo el picking de recepción
            picking.action_confirm()
            picking.write({'state': 'assigned'})

        return picking

    def _create_balance_picking_to_stock(self, crossdock_lines):
        """
        Crea un picking para mover el saldo no distribuido en crossdocking 
        desde WH/Entrada a WH/Existencias
        Este es el último paso del flujo de crossdocking
        """
        StockPicking = self.env['stock.picking']
        entrada_location = self._get_or_create_entrance_location()
        
        # Obtener la ubicación de existencias (stock) del almacén principal
        main_warehouse = self.env['stock.warehouse'].search([
            ('company_id', '=', self.company_id.id)
        ], limit=1)
        stock_location = main_warehouse.lot_stock_id
        
        # Calcular el saldo no distribuido para cada línea de producto
        balance_quantities = {}
        
        # Obtener la distribución calculada para saber cuánto se distribuyó en crossdocking
        if self._are_required_modules_installed():
            distribution = self._calculate_crossdock_distribution(crossdock_lines)
        else:
            distribution = self._calculate_equitable_distribution(crossdock_lines, self.env['stock.warehouse'].search([
                ('company_id', '=', self.company_id.id),
                ('active', '=', True)
            ]))
        
        # Calcular el saldo para cada línea
        for line in crossdock_lines:
            total_qty = line.product_qty
            distributed_qty = 0
            
            # Sumar todas las cantidades distribuidas para esta línea
            for location, items in distribution.items():
                for item in items:
                    if item['line'].id == line.id:
                        distributed_qty += item['quantity']
            
            # Calcular el saldo
            balance_qty = total_qty - distributed_qty
            
            if balance_qty > 0:
                balance_quantities[line.id] = balance_qty
        
        if not balance_quantities:
            return False

        
        existing_picking = self.picking_ids.filtered(
            lambda p: p.location_id.id == entrada_location.id and 
            p.location_dest_id.id == stock_location.id and
            p.state not in ('done', 'cancel') and
            'Saldo Crossdock' in (p.origin or '')
        )
        
        if existing_picking:
            picking = existing_picking[0]
        else:
            internal_picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'internal'),
                ('warehouse_id', '=', main_warehouse.id),
                ('default_location_src_id', '=', entrada_location.id),
                ('default_location_dest_id', '=', stock_location.id),
            ], limit=1)
            
            if not internal_picking_type:
                internal_picking_type = self.env['stock.picking.type'].search([
                    ('code', '=', 'internal'),
                    ('warehouse_id', '=', main_warehouse.id),
                ], limit=1)

            if not main_warehouse.crossdocking_type_id:
                raise ValidationError("No se ha definido el tipo de picking de 'Crossdocking' en el almacén principal.")
            
            picking_vals = {
                'picking_type_id': main_warehouse.crossdocking_type_id.id,
                'partner_id': self.partner_id.id,
                'company_id': self.company_id.id,
                'move_type': 'direct',
                'location_id': entrada_location.id,
                'location_dest_id': stock_location.id,
                'origin': f"{self.name} - Saldo Crossdock",
                'scheduled_date': self.date_planned or fields.Datetime.now(),
                'user_id': False
            }
            
            picking = StockPicking.with_user(SUPERUSER_ID).create(picking_vals)
        
        moves = self.env['stock.move']
        for line_id, quantity in balance_quantities.items():
            line = self.env['purchase.order.line'].browse(line_id)
            
            move_vals = {
                'name': f"Saldo: {line.product_id.display_name} → {stock_location.display_name}",
                'product_id': line.product_id.id,
                'product_uom_qty': quantity,
                'product_uom': line.product_uom.id,
                'location_id': entrada_location.id,
                'location_dest_id': stock_location.id,
                'picking_id': picking.id,
                'partner_id': self.partner_id.id,
                'origin': self.name,
                'state': 'draft',
                'company_id': self.company_id.id,
                'purchase_line_id': line.id,
                'group_id': self.group_id.id,
                'date': line.date_planned or self.date_planned or fields.Datetime.now(),
                'date_deadline': line.date_planned,
                'procure_method': 'make_to_stock',
                'warehouse_id': main_warehouse.id,
            }
            
            move = self.env['stock.move'].create(move_vals)
            moves |= move
        
        if moves:
            moves = moves.filtered(lambda x: x.state not in ('done', 'cancel'))._action_confirm()
            
            seq = 0
            for move in sorted(moves, key=lambda move: move.date):
                seq += 5
                move.sequence = seq
            
            
            
            picking.message_post_with_source(
                'mail.message_origin_link',
                render_values={'self': picking, 'origin': self},
                subtype_xmlid='mail.mt_note',
            )
            
            forward_pickings = self.env['stock.picking']._get_impacted_pickings(moves)
            (picking | forward_pickings).action_confirm()
        
        
        
        
        return picking
    
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
        
        #moves._action_assign()
        forward_pickings = self.env['stock.picking']._get_impacted_pickings(moves)
        (picking | forward_pickings).action_confirm()
        
        
        
        picking.message_post_with_source(
            'mail.message_origin_link',
            render_values={'self': picking, 'origin': self},
            subtype_xmlid='mail.mt_note',
        )

    def _get_main_reception_picking(self):
     
        entrada_location = self._get_or_create_entrance_location()
        
        main_reception_picking = self.picking_ids.filtered(
            lambda p: p.location_dest_id.id == entrada_location.id and 
            p.state not in ('done', 'cancel') and
            'Recepción Crossdock' in (p.origin or '')
        )
        
        return main_reception_picking[0] if main_reception_picking else False

    def _create_crossdocking_pickings_for_lines(self, crossdock_lines):
        
        StockPicking = self.env['stock.picking']
        all_pickings = self.env['stock.picking']
        all_moves = self.env['stock.move']
        
        warehouse_distribution = self._calculate_crossdock_distribution(crossdock_lines)
        
        if not warehouse_distribution:
            return
        
        for ubi, itm in warehouse_distribution.items():

            alm = itm[0]['warehouse'];

            existing_picking = self.picking_ids.filtered(
                lambda p: p.location_dest_id.id == ubi.id and 
                p.state not in ('done', 'cancel') and
                'Crossdock' in (p.origin or '')
            )

            esPrincipal = False;

            main_warehouse = self.picking_type_id.warehouse_id or self.env['stock.warehouse'].search([
            ('company_id', '=', self.company_id.id)
            ], limit=1)

            if main_warehouse.id == alm.id:
                esPrincipal = True;
            
            if not alm.crossdocking_type_id or not alm.crossdocking_location_id or not alm.crossdocking_reception_type_id:
                raise ValidationError("No se ha configurado correctamente el almacén %s para crossdocking. Por favor, revise la configuración." % alm.name)

            if not main_warehouse.crossdocking_type_id:
                raise ValidationError("No se ha definido el tipo de picking de 'Crossdocking' en el almacén principal.")

            if not esPrincipal:


                crossdockingPicking = self._prepare_picking();
                crossdockingPicking.update({
                    'location_dest_id': alm.crossdocking_location_id.id,
                    'location_id': self._get_or_create_entrance_location().id,
                    'origin': f"{self.name} - Crossdock Equitativo {ubi.complete_name}",
                    'picking_type_id': alm.crossdocking_type_id.id
                })


                crosspick = StockPicking.with_user(SUPERUSER_ID).create(crossdockingPicking);
                

                all_pickings |= crosspick;

                picking_moves = self._create_crossdock_moves_for_picking(crosspick, ubi, itm);
                all_moves |= picking_moves;

           

            existing_picking = self.picking_ids.filtered(
                lambda p: p.location_dest_id.id == ubi.id and 
                p.state not in ('done', 'cancel') and
                'Crossdock' in (p.origin or '')
            )
            
            if existing_picking:
                picking = existing_picking[0]
                
            else:
                picking_vals = self._prepare_picking()

                if esPrincipal:
                    picking_vals.update({
                        'location_dest_id': ubi.id,
                        'location_id': self._get_or_create_entrance_location().id,
                        'origin': f"{self.name} - Crossdock Equitativo {ubi.complete_name}",
                        'picking_type_id': main_warehouse.crossdocking_type_id.id
                    })
                else:

                    picking_vals.update({
                        'location_dest_id': ubi.id,
                        'location_id': alm.crossdocking_location_id.id,
                        'origin': f"{self.name} - Crossdock Equitativo {ubi.complete_name}",
                        'picking_type_id': alm.crossdocking_reception_type_id.id
                    })
                
                picking = StockPicking.with_user(SUPERUSER_ID).create(picking_vals)
            
            all_pickings |= picking
            
            picking_moves = self._create_crossdock_moves_for_picking(picking, ubi, itm)
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
            
            # NO asignar inmediatamente - deben esperar a la recepción
            # all_moves._action_assign()
            
            forward_pickings = self.env['stock.picking']._get_impacted_pickings(all_moves)
            (all_pickings | forward_pickings).action_confirm()
            
            for picking in all_pickings:
                if picking.state == 'confirmed':
                    try:
                        picking.write({'state': 'waiting'});
                    except:
                        pass

                    for move in all_moves:
                        if move.move_line_ids:
                            move.move_line_ids.unlink()
                        move.write({
                            'quantity': 0,
                        })
                        
           

    

    def _apply_multiple_rounding(self, quantity, multiple, rounding_method):
        """
        Aplica redondeo basado en múltiplos y método de redondeo para distribución
        """
        import math
        
        if multiple <= 1:
            return int(quantity)
        
        if rounding_method == 'ceil':
            return math.ceil(quantity / multiple) * multiple
        elif rounding_method == 'floor':
            return math.floor(quantity / multiple) * multiple
        else:  # nearest
            return round(quantity / multiple) * multiple

    def _apply_distribution_with_limit_control(self, line, distributions, total_crossdock_quantity, rounding_method):
        """
        Aplica redondeo con control de límites
        IMPORTANTE: total_crossdock_quantity es solo la cantidad para CROSSDOCK, no la línea completa
        """
        import math
        
        multiple = getattr(line, 'distribution_multiple', 1) or 1
        if multiple <= 1:
            return distributions, 0, []
        
        total_distributed = 0
        adjusted_distributions = []
        warnings = []
        
        # Aplicar redondeo a cada distribución
        for dist in distributions:
            cantidad_calculada = dist['quantity']
            
            if rounding_method == 'ceil':
                cantidad_redondeada = math.ceil(cantidad_calculada / multiple) * multiple
            elif rounding_method == 'floor':
                cantidad_redondeada = math.floor(cantidad_calculada / multiple) * multiple
            else:  # nearest
                cantidad_redondeada = round(cantidad_calculada / multiple) * multiple
            
            adjusted_distributions.append({
                'location': dist.get('location'),
                'warehouse': dist.get('warehouse'),
                'rounded_quantity': cantidad_redondeada,
                'line': line
            })
            
            total_distributed += cantidad_redondeada
        
        # Calcular el ajuste necesario para el almacén central
        excess = total_distributed - total_crossdock_quantity
        
        if excess > 0:
            self.write({'exceso': True})
        
        # NO reducir las distribuciones - mantener el redondeo deseado
        final_distributions = []
        for dist in adjusted_distributions:
            if dist['rounded_quantity'] > 0:
                final_distributions.append({
                    'location': dist['location'],
                    'warehouse': dist['warehouse'],
                    'quantity': dist['rounded_quantity'],
                    'line': line,
                    'was_adjusted': False
                })
        
        # El exceso se compensa en la cantidad central (puede ser negativo)
        central_adjustment = -excess
        
        return final_distributions, central_adjustment, warnings

    def _calculate_crossdock_distribution(self, crossdock_lines):
        distribution = {}
        almacenes = []
        almacenes_set = set()

        if not self._are_required_modules_installed():
            return self._calculate_equitable_distribution(crossdock_lines, self.env['stock.warehouse'].search([
                ('company_id', '=', self.company_id.id),
                ('active', '=', True)
            ]));
        
        

        for line in crossdock_lines:
            grupo = line.product_id.warehouse_group_id

            

            if not grupo:
                raise ValidationError("El producto no tiene asignado ningún grupo.");

            grupos = self.env['stock.warehouse.group'].search([
                ('nivel_jerarquia_id.seq', '<=', grupo.nivel_jerarquia_id.seq if grupo and grupo.nivel_jerarquia_id else 0),
            ])

            for g in grupos:
                if g and g.warehouse_ids:
                    for wh in g.warehouse_ids:
                        almacenes_set.add(wh)

        almacenes = list(almacenes_set)

        main_warehouse = self.picking_type_id.warehouse_id or self.env['stock.warehouse'].search([
            ('company_id', '=', self.company_id.id)
        ], limit=1)
        
        if main_warehouse and main_warehouse not in almacenes:
            almacenes.append(main_warehouse)

        

        ubicaciones_lot_stock = []
        ubicacion_principal = main_warehouse.lot_stock_id if main_warehouse else self.picking_type_id.default_location_dest_id
        
        for almacen in almacenes:
            ubicaciones_internas = None

            if self._are_required_modules_installed():
                ubicaciones_internas = self.env['stock.location'].search([
                    ('usage', '=', 'internal'),
                    ('id', 'child_of', almacen.view_location_id.id),
                    ('replenish_location', '=', True),
                ])
                
                if not ubicaciones_internas:
                    ubicaciones_internas = self.env['stock.location'].search([
                        ('usage', '=', 'internal'),
                        ('id', 'child_of', almacen.view_location_id.id),
                        ('replenish_location', '=', True),
                    ])
                    
                if not ubicaciones_internas:
                    ubicaciones_internas = self.env['stock.location'].search([
                        ('usage', '=', 'internal'),
                        ('id', 'child_of', almacen.view_location_id.id),
                    ])
                    
            else:
                ubicaciones_internas = self.env['stock.location'].search([
                    ('usage', '=', 'internal'),
                    ('id', 'child_of', almacen.view_location_id.id),
                    ('replenish_location', '=', True),
                ])
                
                if not ubicaciones_internas:
                    ubicaciones_internas = self.env['stock.location'].search([
                        ('usage', '=', 'internal'),
                        ('id', 'child_of', almacen.view_location_id.id),
                    ])
            
            for ubi in ubicaciones_internas:
                ubicaciones_lot_stock.append((ubi, almacen))
                distribution[ubi] = []

        

        if ubicacion_principal:
            if ubicacion_principal not in distribution:
                almacen_principal = None
                for almacen in almacenes:
                    if ubicacion_principal.id in almacen.view_location_id.with_context(active_test=False).search([
                        ('id', 'child_of', almacen.view_location_id.id)
                    ]).ids:
                        almacen_principal = almacen
                        break
                
                
                if not almacen_principal:
                    almacen_principal = main_warehouse
                
                if almacen_principal:
                    distribution[ubicacion_principal] = []
                    if (ubicacion_principal, almacen_principal) not in ubicaciones_lot_stock:
                        ubicaciones_lot_stock.append((ubicacion_principal, almacen_principal))
        
        for line in crossdock_lines:
            porcentaje = line.line_crossdock_percentage or (self.crossdock_percentage / 100)


            operacion = main_warehouse.crossdocking_type_id;
            
            if operacion and operacion.respeta_multiplos:
                multiple = getattr(line, 'distribution_multiple', 1) or 1
                if multiple > 1 and line.product_qty % multiple != 0:
                    raise ValidationError("La operación respeta multiplos. La línea de orden de compra %s tiene una cantidad total (%s) que no es múltiplo de %s. Por favor, ajuste la cantidad o el múltiplo." % (line.name, line.product_qty, multiple))

            if porcentaje <= 0:
                continue

            cantidad_total = line.product_qty
            cantidad_crossdock_raw = cantidad_total * porcentaje
            cantidad_crossdock = math.floor(cantidad_crossdock_raw) 
            cantidad_principal = cantidad_total - cantidad_crossdock

            almacen_principal = None
            for ubi, alm in ubicaciones_lot_stock:
                if ubi == ubicacion_principal:
                    almacen_principal = alm
                    break
            
            if not almacen_principal and ubicacion_principal and main_warehouse:
                almacen_principal = main_warehouse
                if (ubicacion_principal, almacen_principal) not in ubicaciones_lot_stock:
                    ubicaciones_lot_stock.append((ubicacion_principal, almacen_principal))
            
            if not almacen_principal:
                continue

            capacidades_maximas = {}
            total_capacidad = 0
            
            
            for ubi, alm in ubicaciones_lot_stock:
                if ubi == ubicacion_principal:
                    continue
                    
                capacidad_maxima = 0
                categoria_encontrada = False
                
                has_warehouse_groups = hasattr(alm, 'warehouse_group_ids') and alm.warehouse_group_ids
                
                if has_warehouse_groups and alm.warehouse_group_ids:
                    
                    for grupo in alm.warehouse_group_ids:
                        if hasattr(grupo, 'category_rule_ids') and grupo.category_rule_ids:
                            
                            for cat in grupo.category_rule_ids:
                                
                                if cat.categ_id.id == line.product_id.categ_id.id:
                                    categoria_encontrada = True
                                    if hasattr(cat, 'max_qty') and cat.max_qty:
                                        capacidad_maxima = cat.max_qty
                                        break;
                        if capacidad_maxima > 0:
                            break
                    
                    if not categoria_encontrada:
                        
                        # Solo considerar ubicaciones con automate_reordering = True
                        if hasattr(ubi, 'automate_reordering') and ubi.automate_reordering:
                            if hasattr(ubi, 'default_max_qty') and ubi.default_max_qty:
                                capacidad_maxima = ubi.default_max_qty
                            
                        else:
                            capacidad_maxima = 0
                    elif capacidad_maxima == 0:
                        
                        if hasattr(ubi, 'default_max_qty') and ubi.default_max_qty:
                            capacidad_maxima = ubi.default_max_qty
                        
                else:
                    
                    if hasattr(ubi, 'automate_reordering') and ubi.automate_reordering:
                        
                        if hasattr(ubi, 'default_max_qty') and ubi.default_max_qty:
                            capacidad_maxima = ubi.default_max_qty
                            
                        
                    else:
                        capacidad_maxima = 0
                
                capacidades_maximas[ubi] = capacidad_maxima
                total_capacidad += capacidad_maxima

            multiple = getattr(line, 'distribution_multiple', 1) or 1
            rounding_method = self.distribution_rounding_method or 'nearest'

            pending_distributions = []
            
            for ubi, alm in ubicaciones_lot_stock:
                if ubi == ubicacion_principal:
                    continue
                    
                capacidad_maxima = capacidades_maximas.get(ubi, 0)
                
                if capacidad_maxima > 0 and total_capacidad > 0:
                    # Calcular porcentaje (siempre con round)
                    porcentaje_ubicacion = capacidad_maxima / total_capacidad
                    cantidad_calculada = math.floor(cantidad_crossdock * porcentaje_ubicacion)
                    
                    if cantidad_calculada > 0:
                        pending_distributions.append({
                            'location': ubi,
                            'warehouse': alm,
                            'quantity': cantidad_calculada
                        })
            
            if pending_distributions:
                final_distributions, central_adjustment, warnings = self._apply_distribution_with_limit_control(
                    line, 
                    pending_distributions, 
                    cantidad_crossdock, 
                    rounding_method
                )
                
                for warning in warnings:
                    self.message_post(body=warning)
                
                for dist in final_distributions:
                    distribution[dist['location']].append({
                        'line': line,
                        'quantity': dist['quantity'],
                        'warehouse': dist['warehouse']
                    })
                
                # Calcular cantidad restante después del control de límites
                total_distributed = sum(dist['quantity'] for dist in final_distributions)
                cantidad_para_principal_ajustada = cantidad_total - total_distributed
            else:
                cantidad_para_principal_ajustada = cantidad_principal

            
            cantidad_distribuida_destinos = 0
            for dist in distribution:
                if dist != ubicacion_principal:
                    for item in distribution[dist]:
                        if item['line'] == line:
                            cantidad_distribuida_destinos += item['quantity']

            # El saldo para el principal es el pedido menos lo distribuido
            cantidad_final_principal = line.product_qty - cantidad_distribuida_destinos
            if cantidad_final_principal < 0:
                cantidad_final_principal = 0

            if ubicacion_principal and cantidad_final_principal > 0:
                if ubicacion_principal in distribution and almacen_principal:
                    distribution[ubicacion_principal].append({
                        'line': line,
                        'quantity': cantidad_final_principal,
                        'warehouse': almacen_principal
                    })
                        
            

        distribuciones_con_contenido = {k: v for k, v in distribution.items() if v}
        

        

        return distribuciones_con_contenido

    def _create_crossdock_moves_for_picking(self, picking, location, lines_data):
        moves = self.env['stock.move']

        # Agrupar por producto
        product_quantities = {}
        for line_data in lines_data:
            line = line_data['line']
            quantity = line_data['quantity']
            product_id = line.product_id.id
            warehouse = line_data.get('warehouse')
            if quantity <= 0:
                continue
            if product_id not in product_quantities:
                product_quantities[product_id] = {
                    'line': line,
                    'quantity': 0,
                    'warehouse': warehouse
                }
            product_quantities[product_id]['quantity'] += quantity


        for idx, line_data in enumerate(lines_data):
            _logger.info(f"  [{idx}] Producto: {line_data['line'].product_id.display_name}, Cantidad: {line_data['quantity']}")

        for product_id, data in product_quantities.items():
            line = data['line']
            quantity = data['quantity']
            warehouse = data['warehouse']

            move_vals = {
                'name': f"Crossdock: {line.product_id.display_name} → {picking.location_dest_id.display_name}",
                'product_id': line.product_id.id,
                'product_uom_qty': quantity,
                'quantity': 0,
                'product_uom': line.product_uom.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
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
    
    def _get_or_create_entrance_location(self):
        
        main_warehouse = self.picking_type_id.warehouse_id or self.env['stock.warehouse'].search([
            ('company_id', '=', self.company_id.id)
        ], limit=1)
        
        if main_warehouse and main_warehouse.wh_input_stock_loc_id:
            return main_warehouse.wh_input_stock_loc_id
            
        # Buscar ubicación de entrada por nombre
        entrance_location = self.env['stock.location'].search([
            ('usage', '=', 'internal'),
            ('company_id', '=', self.company_id.id),
            ('id', 'child_of', main_warehouse.view_location_id.id if main_warehouse else False),
            '|', ('name', 'ilike', 'entrada'),
                 ('name', 'ilike', 'input'),
        ], limit=1)
        
        if entrance_location:
            return entrance_location
        
        if main_warehouse:
            receipts_picking_type = self.env['stock.picking.type'].search([
                ('warehouse_id', '=', main_warehouse.id),
                ('code', '=', 'incoming')
            ], limit=1)
            
            if receipts_picking_type and receipts_picking_type.default_location_dest_id:
                return receipts_picking_type.default_location_dest_id
        
        if main_warehouse and main_warehouse.lot_stock_id:
            return main_warehouse.lot_stock_id
        
        default_location = self.picking_type_id.default_location_src_id
        if default_location:
            return default_location
        

