from odoo import models, api, fields
import json


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.onchange('grid')
    def _apply_grid(self):
        
        result = super(PurchaseOrder, self)._apply_grid()
        
        if self.grid and self.grid_update:
            grid = json.loads(self.grid)
            
            product_template_id = grid.get('product_template_id')
            if product_template_id:
                product_template = self.env['product.template'].browse(product_template_id)
                
                
                affected_products = set()
                
                for cell in grid.get('changes', []):
                    ptav_ids = cell.get('ptav_ids', [])
                    if ptav_ids:
                        combination = self.env['product.template.attribute.value'].browse(ptav_ids)
                        
                        product = product_template._create_product_variant(combination)
                        if product:
                            affected_products.add(product.id)
                
                for line in self.order_line.filtered(lambda l: l.product_id.id in affected_products):
                    
                    # Aplicar crossdock
                    if self.crossdock_enabled:
                        line.use_crossdock = True
                        line.line_crossdock_percentage = self.crossdock_percentage / 100.0
                    
                    # Aplicar múltiplo de distribución
                    if line.distribution_multiple > 1 and line.product_qty > 0:
                        self._apply_multiple_to_line(line)
        
        return result
    
    def _apply_multiple_to_line(self, line):
        if not line or not line.distribution_multiple or line.distribution_multiple <= 1:
            return
        
        multiple = line.distribution_multiple
        current_qty = line.product_qty
        
        rounding_method = None
        
        if hasattr(self, 'order_type') and self.order_type:
            if hasattr(self.order_type, 'distribution_rounding_method'):
                rounding_method = self.order_type.distribution_rounding_method
        elif hasattr(self, 'type_id') and self.type_id:
            if hasattr(self.type_id, 'distribution_rounding_method'):
                rounding_method = self.type_id.distribution_rounding_method
        
        if not rounding_method:
            rounding_method = self.distribution_rounding_method or 'nearest'
        
        import math
        
        if rounding_method == 'ceil':
            current_qty = math.ceil(current_qty)
            while current_qty % multiple != 0:
                current_qty += 1
        elif rounding_method == 'floor':
            current_qty = math.floor(current_qty)
            while current_qty % multiple != 0:
                current_qty -= 1
            if current_qty < 0:
                current_qty = 0
        else:  # nearest
            lower = current_qty
            while lower % multiple != 0:
                lower -= 1
            upper = current_qty
            while upper % multiple != 0:
                upper += 1
            if (current_qty - lower) <= (upper - current_qty):
                current_qty = lower
            else:
                current_qty = upper
        
        if current_qty != line.product_qty:
            line.product_qty = current_qty