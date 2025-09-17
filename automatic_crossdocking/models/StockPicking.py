from odoo import models, api, fields;




class StockPicking(models.Model):
    _inherit = 'stock.picking';

    @api.model
    def updatePickingQuantity(self, picking_id, product_id, new_quantity):
        try:
            picking = self.env['stock.picking'].browse(picking_id)
            if not picking.exists():
                return {'error': 'Picking not found'}
            
            # Validar que el picking esté en estado editable
            if picking.state not in ('confirmed', 'waiting'):
                return {
                    'error': f'No se puede editar este picking. Estado actual: {picking.state}. Solo se permiten ediciones en pickings con estado "Confirmado" o "En espera".'
                }
            
            original_state = picking.state
            
            move_line = picking.move_ids_without_package.filtered(
                lambda m: m.product_id.id == int(product_id)
            )
            
            if not move_line:
                return {'error': 'Product not found in picking'}
            
            if len(move_line) > 1:
                move_line = move_line[0]
            
            old_quantity = move_line.product_uom_qty
            quantity_difference = float(new_quantity) - old_quantity
            
            move_line.with_context(do_not_propagate=True, no_recompute=True).write({
                'product_uom_qty': float(new_quantity),
                'quantity': float(new_quantity)
            })
            
            purchase_line = move_line.purchase_line_id
            balance_updated = False
            
            if purchase_line and purchase_line.order_id.crossdock_enabled:
                purchase_order = purchase_line.order_id
                balance_updated = self._update_balance_picking_quantity(
                    purchase_order, purchase_line, -quantity_difference  # Signo contrario
                )
            
            self._update_reception_picking(picking, move_line, old_quantity, float(new_quantity))
            
            if picking.state != original_state:
                picking.write({'state': original_state})

            message = f'Cantidad actualizada a {new_quantity} unidades'
            if balance_updated:
                if quantity_difference > 0:
                    message += f'. Se redujeron {quantity_difference} unidades del saldo principal.'
                elif quantity_difference < 0:
                    message += f'. Se agregaron {abs(quantity_difference)} unidades al saldo principal.'

            return {
                'success': True,
                'message': message,
                'balance_updated': balance_updated,
                'move_id': move_line.id,
                'quantity_difference': quantity_difference
            }
            
        except Exception as e:
            return {'error': str(e)}
    
    def _update_reception_picking(self, picking, move_line, old_quantity, new_quantity):
        
        purchase_line = move_line.purchase_line_id
        if not purchase_line or not purchase_line.order_id.crossdock_enabled:
            return
        

        
        purchase_order = purchase_line.order_id
        
        if not 'Crossdock' in (picking.origin or ''):
            return
        
        entrance_location = purchase_order._get_or_create_entrance_location()
        reception_pickings = purchase_order.picking_ids.filtered(
            lambda p: p.location_dest_id.id == entrance_location.id and 
                     p.state not in ('done', 'cancel') and
                     'Recepción Crossdock' in (p.origin or '')
        )
        
        if not reception_pickings:
            return
        
        for reception_picking in reception_pickings:
            reception_move = reception_picking.move_ids_without_package.filtered(
                lambda m: m.purchase_line_id.id == purchase_line.id
            )
            
            if reception_move:
                # Calcular el total de la cantidad distribuida en todos los pickings de crossdocking
                crossdock_pickings = purchase_order.picking_ids.filtered(
                    lambda p: 'Crossdock' in (p.origin or '') and 
                             p.id != reception_picking.id and
                             p.state not in ('done', 'cancel')
                )
                
                total_distributed = 0
                for crossdock_picking in crossdock_pickings:
                    for move in crossdock_picking.move_ids_without_package:
                        if move.purchase_line_id.id == purchase_line.id:
                            total_distributed += move.product_uom_qty
                
                # Actualizar la cantidad en el picking de recepción para que sea igual al total distribuido
                if total_distributed != reception_move.product_uom_qty:
                    reception_move.product_uom_qty = total_distributed

        reception_pickings.write({'state': 'confirmed'});

    @api.model
    def updateMainReceptionQuantity(self, picking_id, product_id, new_quantity, old_quantity):
        
        try:
            picking = self.env['stock.picking'].browse(picking_id)
            if not picking.exists():
                return {'error': 'Picking de recepción no encontrado'}
            
            # Verificar que es un picking de recepción hacia WH/Entrada
            if 'Recepción Crossdock' not in (picking.origin or ''):
                return {'error': 'Este no es un picking de recepción principal'}
            
            move_line = picking.move_ids_without_package.filtered(
                lambda m: m.product_id.id == int(product_id)
            )
            
            if not move_line:
                return {'error': 'Producto no encontrado en el picking de recepción'}
            
            if len(move_line) > 1:
                move_line = move_line[0]
            
            purchase_line = move_line.purchase_line_id
            if not purchase_line:
                return {'error': 'No se encontró la línea de compra asociada'}
            
            purchase_order = purchase_line.order_id
            
            quantity_difference = float(new_quantity) - float(old_quantity)
            
            original_state = picking.state
            move_line.with_context(do_not_propagate=True, no_recompute=True).write({
                'product_uom_qty': float(new_quantity),
                'quantity': float(new_quantity)
            })
            
            balance_updated = self._update_balance_picking_quantity(
                purchase_order, purchase_line, quantity_difference
            )
            
            if picking.state != original_state:
                picking.write({'state': original_state})
            
            message = f'Recepción actualizada a {new_quantity} unidades'
            if balance_updated:
                if quantity_difference > 0:
                    message += f'. Se agregaron {quantity_difference} unidades al saldo principal.'
                elif quantity_difference < 0:
                    message += f'. Se redujeron {abs(quantity_difference)} unidades del saldo principal.'
            
            return {
                'success': True,
                'message': message,
                'balance_updated': balance_updated,
                'move_id': move_line.id,
                'quantity_difference': quantity_difference
            }
            
        except Exception as e:
            _logger.error(f"Error al actualizar recepción principal: {str(e)}")
            return {'error': f'Error interno: {str(e)}'}
    
    def _update_balance_picking_quantity(self, purchase_order, purchase_line, quantity_difference):
        
        try:
            entrance_location = purchase_order._get_or_create_entrance_location()
            
            main_warehouse = purchase_order.picking_type_id.warehouse_id or self.env['stock.warehouse'].search([
                ('company_id', '=', purchase_order.company_id.id)
            ], limit=1)
            
            if not main_warehouse:
                return False
            
            stock_location = main_warehouse.lot_stock_id
            
            balance_pickings = purchase_order.picking_ids.filtered(
                lambda p: p.location_id.id == entrance_location.id and 
                         p.location_dest_id.id == stock_location.id and
                         p.state not in ('done', 'cancel') and
                         'Saldo no distribuido' in (p.origin or '')
            )
            
            if not balance_pickings:
                return False
            
            for balance_picking in balance_pickings:
                balance_move = balance_picking.move_ids_without_package.filtered(
                    lambda m: m.purchase_line_id.id == purchase_line.id
                )
                
                if balance_move:
                    if len(balance_move) > 1:
                        balance_move = balance_move[0]
                    
                    new_balance_quantity = balance_move.product_uom_qty + quantity_difference
                    
                    if new_balance_quantity < 0:
                        new_balance_quantity = 0
                    
                    original_state = balance_picking.state
                    balance_move.with_context(do_not_propagate=True, no_recompute=True).write({
                        'product_uom_qty': new_balance_quantity,
                        'quantity': new_balance_quantity
                    })
                    
                    # Restaurar estado original
                    if balance_picking.state != original_state:
                        balance_picking.write({'state': original_state})
                    
                    _logger.info(f"Saldo actualizado: {balance_move.product_uom_qty} -> {new_balance_quantity}")
                    return True
            
            return False
            
        except Exception as e:
            return False