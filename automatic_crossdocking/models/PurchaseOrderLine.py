from odoo import api, models, fields
from odoo.exceptions import ValidationError, UserError
import math

class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    use_crossdock = fields.Boolean(
        string="Usar Cross-Docking",
        help="Si está activo, la línea se enviará directamente al punto de venta."
    )
    
    line_crossdock_percentage = fields.Float(
        string="% Cross-Docking (Línea)",
        help="Porcentaje de la cantidad que irá a cross-docking.",
        default=0.0
    )
    
    distribution_multiple = fields.Integer(
        string="Múltiplo de Distribución",
        default=1,
        help="Ej: Si es 6, la cantidad se redondea a múltiplos de 6 (cajas)."
    )

    
    @api.constrains('line_crossdock_percentage')
    def _check_crossdock_percentage_constrains(self):
        for line in self:
            if line.order_id.state in ('purchase', 'done'):
                raise ValidationError(
                    f"No se puede modificar el porcentaje de crossdock en la línea {line.product_id.name} "
                    f"después de confirmar la orden de compra."
                )

    def _apply_crossdock_defaults(self):
        """Método auxiliar para aplicar configuraciones de crossdock"""
        for line in self:
            if line.order_id.crossdock_enabled:
                line.use_crossdock = True
                
                # Prioridad: producto > orden
                if hasattr(line.product_id, 'crossdock_percentage') and line.product_id.crossdock_percentage:
                    line.line_crossdock_percentage = line.product_id.crossdock_percentage / 100.0
                elif hasattr(line.order_id, 'crossdock_percentage'):
                    line.line_crossdock_percentage = line.order_id.crossdock_percentage / 100.0

    @api.onchange('product_id')
    def _onchange_product_id_crossdock(self):
        self._apply_crossdock_defaults()

    @api.onchange('product_qty')
    def onChangeJustProductQty(self):
        self._onchange_distribution_multiple();

    @api.onchange('distribution_multiple')
    def onChangeJustDistributionMultiple(self):
        self._onchange_distribution_multiple()

    @api.onchange('distribution_multiple', 'product_qty')
    def _onchange_distribution_multiple(self):
        for line in self:
            if line.distribution_multiple > 1:
                
                # Obtener el múltiplo configurado
                multiple = line.distribution_multiple
                current_qty = line.product_qty or 0
                rounding_method = None
                
                if hasattr(line.order_id, 'order_type') and line.order_id.order_type:
                    if hasattr(line.order_id.order_type, 'distribution_rounding_method'):
                        rounding_method = line.order_id.order_type.distribution_rounding_method
                        
                elif hasattr(line.order_id, 'type_id') and line.order_id.type_id:
                    if hasattr(line.order_id.type_id, 'distribution_rounding_method'):
                        rounding_method = line.order_id.type_id.distribution_rounding_method
                        
                # Si no se encontró en el tipo, buscar en la orden
                if not rounding_method and hasattr(line.order_id, 'distribution_rounding_method'):
                    rounding_method = line.order_id.distribution_rounding_method
                
                # Valor predeterminado
                if not rounding_method:
                    rounding_method = 'nearest'
                
                
                if rounding_method == 'ceil':
                    current_qty = math.ceil(current_qty);
                    while current_qty % multiple != 0:
                        current_qty += 1

                elif rounding_method == 'floor':
                    current_qty = math.floor(current_qty);
                    while current_qty % multiple != 0:
                        current_qty -= 1
                    if current_qty < 0:
                        current_qty = 0

                else: # nearest
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

                
                line.product_qty = current_qty;

    def write(self, vals):
        if 'line_crossdock_percentage' in vals:
            if not self.env.user.has_group('automatic_crossdocking.group_crossdock_editors'):
                raise UserError("No tiene permisos para modificar el porcentaje de cross-docking. Contacte al administrador.")
            
            percentage = vals['line_crossdock_percentage']
            if percentage < 0 or percentage > 100:
                raise ValidationError("El porcentaje de cross-docking debe estar entre 0 y 100.")
        
        if 'distribution_multiple' in vals:
            if vals['distribution_multiple'] < 1:
                raise ValidationError("El múltiplo de distribución debe ser mayor o igual a 1.")
        
        result = super(PurchaseOrderLine, self).write(vals)
        
        # Aplicar configuraciones de crossdock después del write si es necesario
        if any(field in vals for field in ['product_id', 'order_id']):
            self._apply_crossdock_defaults()
        
        return result

    @api.constrains('line_crossdock_percentage')
    def _check_line_crossdock_percentage(self):
        for line in self:
            if line.line_crossdock_percentage < 0 or line.line_crossdock_percentage > 100:
                raise ValidationError("El porcentaje de cross-docking debe estar entre 0 y 100.")

    @api.constrains('distribution_multiple')
    def _check_distribution_multiple(self):
        for line in self:
            if line.distribution_multiple < 1:
                raise ValidationError("El múltiplo de distribución debe ser mayor o igual a 1.")

    @api.model_create_multi
    def create(self, vals_list):
        # Aplicar configuraciones de crossdock antes de crear
        for vals in vals_list:
            if 'order_id' in vals:
                order = self.env['purchase.order'].browse(vals['order_id'])
                if order.crossdock_enabled:
                    if 'use_crossdock' not in vals:
                        vals['use_crossdock'] = True
                    
                    if 'line_crossdock_percentage' not in vals:
                        # Verificar si el producto tiene porcentaje específico
                        product_id = vals.get('product_id')
                        if product_id:
                            product = self.env['product.product'].browse(product_id)
                            if hasattr(product, 'crossdock_percentage') and product.crossdock_percentage:
                                vals['line_crossdock_percentage'] = product.crossdock_percentage / 100.0
                            else:
                                vals['line_crossdock_percentage'] = order.crossdock_percentage / 100.0
                        else:
                            vals['line_crossdock_percentage'] = order.crossdock_percentage / 100.0
                
                # Aplicar múltiplo si hay cantidad y múltiplo > 1
                if 'product_qty' in vals and vals.get('distribution_multiple', 1) > 1:
                    multiple = vals.get('distribution_multiple', 1)
                    qty = vals['product_qty']
                    
                    # Aplicar redondeo según el método configurado
                    rounding_method = self._get_rounding_method(order)
                    vals['product_qty'] = self._apply_multiple_to_qty(qty, multiple, rounding_method)
        
        lines = super(PurchaseOrderLine, self).create(vals_list)
        
        return lines
    
    def _get_rounding_method(self, order):
        """
        Obtiene el método de redondeo adecuado de la orden o tipo de orden
        """
        rounding_method = None
        
        # Primero verificar si hay un tipo de orden con configuración
        if hasattr(order, 'order_type') and order.order_type:
            if hasattr(order.order_type, 'distribution_rounding_method'):
                rounding_method = order.order_type.distribution_rounding_method
        elif hasattr(order, 'type_id') and order.type_id:
            if hasattr(order.type_id, 'distribution_rounding_method'):
                rounding_method = order.type_id.distribution_rounding_method
        
        # Si no hay método en el tipo, usar el de la orden
        if not rounding_method and hasattr(order, 'distribution_rounding_method'):
            rounding_method = order.distribution_rounding_method
        
        # Valor predeterminado
        if not rounding_method:
            rounding_method = 'nearest'
        
        return rounding_method
    
    def _apply_multiple_to_qty(self, qty, multiple, rounding_method):
        """
        Aplica múltiplo a una cantidad según el método de redondeo
        """
        import math
        
        if multiple <= 1 or qty <= 0:
            return qty
        
        if rounding_method == 'ceil':
            qty = math.ceil(qty)
            while qty % multiple != 0:
                qty += 1
        elif rounding_method == 'floor':
            qty = math.floor(qty)
            while qty % multiple != 0:
                qty -= 1
            if qty < 0:
                qty = 0
        else:  # nearest
            lower = qty
            while lower % multiple != 0:
                lower -= 1
            upper = qty
            while upper % multiple != 0:
                upper += 1
            if (qty - lower) <= (upper - qty):
                qty = lower
            else:
                qty = upper
        
        return qty