from odoo import models, api, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    mutiplos_distribucion = fields.Integer(
        string='Múltiplos de Distribución',
        default=1,
        help='Cantidad mínima de unidades que se deben pedir o distribuir en múltiplos de este número.'
    )

    def write(self, vals):
        if 'mutiplos_distribucion' in vals:
            if vals['mutiplos_distribucion'] < 1:
                raise ValueError("El campo 'Múltiplos de Distribución' debe ser un número entero positivo mayor o igual a 1.")
            
            # Sincronizar a variantes que NO tengan override personalizado
            for record in self:
                for variant in record.product_variant_ids:
                    # Solo actualizar si la variante no tiene un valor personalizado
                    if not variant.mutiplos_distribucion_override:
                        variant.mutiplos_distribucion = vals['mutiplos_distribucion']
        
        return super().write(vals)