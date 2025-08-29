from odoo import api, models, fields
from odoo.exceptions import ValidationError, UserError

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

    @api.onchange('product_id')
    def _onchange_product_id_crossdock(self):
        for line in self:
            if line.order_id.crossdock_enabled:
                line.use_crossdock = True
                # Get percentage from order or product if available
                if hasattr(line.order_id, 'crossdock_percentage'):
                    line.line_crossdock_percentage = line.order_id.crossdock_percentage / 100.0
                
                # Also check if product has specific crossdock settings
                product = line.product_id
                if hasattr(product, 'crossdock_percentage') and product.crossdock_percentage:
                    line.line_crossdock_percentage = product.crossdock_percentage / 100.0

    @api.onchange('distribution_multiple', 'product_uom_qty')
    def _onchange_distribution_multiple(self):
        for line in self:
            if line.distribution_multiple > 1 and line.product_uom_qty:
                multiple = line.distribution_multiple
                current_qty = line.product_uom_qty
                # Round to nearest multiple
                adjusted_qty = round(current_qty / multiple) * multiple
                if adjusted_qty <= 0:
                    adjusted_qty = multiple  # At least one multiple
                line.product_uom_qty = adjusted_qty

    def write(self, vals):
        if 'line_crossdock_percentage' in vals:
            if not self.env.user.has_group('automatic_crossdocking.group_crossdock_editors'):
                raise UserError("No tiene permisos para modificar el porcentaje de cross-docking. Contacte al administrador.")
            
            percentage = vals['line_crossdock_percentage']
            if percentage < 0 or percentage > 100:
                raise ValidationError("El porcentaje de cross-docking debe estar entre 0 y 100.")
        
        # Handle distribution multiple validation
        if 'distribution_multiple' in vals:
            if vals['distribution_multiple'] < 1:
                raise ValidationError("El múltiplo de distribución debe ser mayor o igual a 1.")
        
        return super(PurchaseOrderLine, self).write(vals)

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

   