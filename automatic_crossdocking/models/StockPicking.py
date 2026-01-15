from odoo import models, api, fields

import logging;
_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

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
            })
            
            purchase_line = move_line.purchase_line_id
            surplus_updated = False
            
            if purchase_line and purchase_line.order_id.crossdock_enabled:
                purchase_order = purchase_line.order_id
                # CAMBIO: Llamar al método para actualizar el picking de sobrante
                surplus_updated = self._update_surplus_picking_quantity(
                    purchase_order, purchase_line, -quantity_difference  # Signo contrario
                )
            
            picking.write({'state': original_state})

            message = f'Cantidad actualizada a {new_quantity} unidades'
            if surplus_updated:
                if quantity_difference > 0:
                    message += f'. Se redujeron {quantity_difference} unidades del sobrante.'
                elif quantity_difference < 0:
                    message += f'. Se agregaron {abs(quantity_difference)} unidades al sobrante.'

            return {
                'success': True,
                'message': message,
                'surplus_updated': surplus_updated,
                'move_id': move_line.id,
                'quantity_difference': quantity_difference
            }
            
        except Exception as e:
            return {'error': str(e)}
    
    def _update_surplus_picking_quantity(self, purchase_order, purchase_line, quantity_difference):
        """
        Actualiza el picking de sobrante/saldo (WH/Entrada → WH/Existencia)
        """
        try:
            entrance_location = purchase_order._get_or_create_entrance_location()
            
            main_warehouse = purchase_order.picking_type_id.warehouse_id or self.env['stock.warehouse'].search([
                ('company_id', '=', purchase_order.company_id.id)
            ], limit=1)
            
            if not main_warehouse:
                _logger.warning("No se encontró almacén principal")
                return False
            
            stock_location = main_warehouse.lot_stock_id
            
            surplus_pickings = purchase_order.picking_ids.filtered(
                lambda p: p.location_id.id == entrance_location.id and 
                         p.location_dest_id.id == stock_location.id)
            
            if not surplus_pickings:
                _logger.warning(f"No se encontraron pickings de sobrante para la orden {purchase_order.name}")
                return False
            
            for surplus_picking in surplus_pickings:
                surplus_move = surplus_picking.move_ids_without_package.filtered(
                    lambda m: m.purchase_line_id.id == purchase_line.id
                )
                
                if surplus_move:
                    if len(surplus_move) > 1:
                        surplus_move = surplus_move[0]
                    
                    old_surplus_quantity = surplus_move.product_uom_qty
                    new_surplus_quantity = old_surplus_quantity + quantity_difference
                    
                    if new_surplus_quantity < 0:
                        new_surplus_quantity = 0
                    
                    original_state = surplus_picking.state
                    surplus_move.with_context(do_not_propagate=True, no_recompute=True).write({
                        'product_uom_qty': new_surplus_quantity,
                    })
                    
                    if surplus_picking.state != original_state:
                        surplus_picking.write({'state': original_state})
                    
                    
                    return True
            
            return False
            
        except Exception as e:
            _logger.error(f"Error al actualizar picking de sobrante: {str(e)}")
            return False

    def button_validate(self):
        result = super(StockPicking, self).button_validate()
        
        for picking in self:

            
            if picking._is_crossdock_reception_picking():
                picking._activate_dependent_crossdock_pickings();
        

        
        return result
    

    def _activate_dependent_crossdock_pickings_transport(self):

    
        _logger.info("SE ENTRO A CONFIRMAR PICKING");
        picking_receptor = self.env['stock.picking'].search([
            ('location_id', '=', self.location_dest_id.id),
        ], limit=1);
    
        picking_receptor.write({'state': 'assigned'});

    def _is_transport_picking(self):
        
        almacenes = self.env['stock.warehouse'].search([]);
    
        for almacen in almacenes:
            if almacen.crossdocking_location_id.id == self.location_id.id:
                return True

    def _is_crossdock_reception_picking(self):
        return (
            'Recepción Crossdock' in (self.origin or '')
        )
    
    def _activate_dependent_crossdock_pickings(self):
        try:
            purchase_order = self.purchase_id
            if not purchase_order or not purchase_order.crossdock_enabled:
                return
            
            entrada_location = purchase_order._get_or_create_entrance_location()
            
            dependent_pickings = purchase_order.picking_ids.filtered(
                lambda p: (
                    p.state in ('waiting', 'confirmed') and
                    p.id != self.id
                )
            )

            

            
            
            if dependent_pickings:
                activated_pickings = []
                
                for picking in dependent_pickings:
                    for move in picking.move_ids:
                        move.write({'quantity': move.product_uom_qty});
                    try:
                        picking.write({'state': 'assigned'});
                        activated_pickings.append(picking.name)
                    except Exception as e:
                        _logger.warning(f"No se pudo activar el picking {picking.name}: {str(e)}")
                
                
                    
        except Exception as e:
            _logger.error(f"Error al activar pickings dependientes: {str(e)}")
    
