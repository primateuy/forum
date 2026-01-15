from odoo import fields, api, models;




class ProductProduct(models.Model):
    _inherit = 'product.product'

    mutiplos_distribucion = fields.Integer(
        string='Múltiplos de Distribución',
        default=1,
        help='Cantidad mínima de unidades. Si está vacío, se usa el valor de la plantilla.'
    )
    
    mutiplos_distribucion_override = fields.Boolean(
        string='Override Múltiplos',
        default=False,
        help='Indica si esta variante tiene un valor personalizado que no debe sincronizarse con la plantilla.'
    )

    def write(self, vals):
        # Si se modifica mutiplos_distribucion directamente en la variante, marcar como override
        if 'mutiplos_distribucion' in vals:
            if vals['mutiplos_distribucion'] < 1:
                raise ValueError("El campo 'Múltiplos de Distribución' debe ser un número entero positivo mayor o igual a 1.")
            
            # Marcar que esta variante tiene un valor personalizado
            vals['mutiplos_distribucion_override'] = True
        
        # Si se desmarca el override, sincronizar con el template
        if 'mutiplos_distribucion_override' in vals and not vals['mutiplos_distribucion_override']:
            for record in self:
                vals['mutiplos_distribucion'] = record.product_tmpl_id.mutiplos_distribucion
        
        return super().write(vals)

    @api.onchange('mutiplos_distribucion_override')
    def _onchange_mutiplos_override(self):
        """Cuando se desmarca el override, restaurar el valor del template"""
        if not self.mutiplos_distribucion_override and self.product_tmpl_id:
            self.mutiplos_distribucion = self.product_tmpl_id.mutiplos_distribucion