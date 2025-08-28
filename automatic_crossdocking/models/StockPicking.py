from odoo import models, api, fields;


import logging;

_logger = logging.getLogger(__name__);



class StockPicking(models.Model):
    _inherit = 'stock.picking';

    @api.model
    def updatePickingQuantity(self, picking_id, product_id, new_quantity):
        try:
            picking = self.env['stock.picking'].browse(picking_id)
            if not picking.exists():
                return {'error': 'Picking not found'}
            
            # Find the move line
            move_line = picking.move_ids_without_package.filtered(
                lambda m: m.product_id.id == int(product_id)
            )
            
            if not move_line:
                return {'error': 'Product not found in picking'}
            
            if len(move_line) > 1:
                move_line = move_line[0]
            move_line.product_uom_qty = float(new_quantity)
            
            return {
                'success': True,
                'message': f'Updated quantity to {new_quantity}',
                'move_id': move_line.id
            }
            
        except Exception as e:
            return {'error': str(e)}