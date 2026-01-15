from odoo import api, models, fields
from odoo.exceptions import ValidationError, UserError
import math
import logging;

_logger = logging.getLogger(__name__)

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


    def _get_default_distribution_multiple(self):
        
        multiple = self.product_id.mutiplos_distribucion or 0
        
        # ✅ Si es 0, retornar 1
        if multiple == 0:
            return 1
        
        return multiple
    
    distribution_multiple = fields.Integer(
        string="Múltiplo de Distribución",
        default=_get_default_distribution_multiple,
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
                
                # # Cargar múltiplo desde reglas de reabastecimiento si el módulo está instalado
                # line._load_multiple_from_reorder_rules()

    # def _load_multiple_from_reorder_rules(self):
    #     """Cargar el múltiplo desde las reglas de reabastecimiento o desde el producto"""
    #     if not self.product_id:
    #         return
        
    #     # PRIMERO: Intentar obtener desde product_template.mutiplos_distribucion
    #     if hasattr(self.product_id.product_tmpl_id, 'mutiplos_distribucion'):
    #         if self.product_id.product_tmpl_id.mutiplos_distribucion > 1:
    #             self.distribution_multiple = self.product_id.product_tmpl_id.mutiplos_distribucion
    #             return
        
    #     # Verificar si los módulos requeridos están instalados
    #     if not self._are_required_modules_installed():
    #         return
        
    #     # Buscar reglas de reabastecimiento para este producto
    #     reorder_rules = self.env['stock.warehouse.orderpoint'].search([
    #         ('product_id', '=', self.product_id.id),
    #         ('active', '=', True)
    #     ])

    #     if len(reorder_rules) > 1:
    #         product_cat = self.product_id.categ_id;
    #         if not product_cat:
    #             return;

    #         product_cluster = self.product_id.warehouse_group_id;
    #         if not product_cluster:
    #             return;

    #         for cat in product_cluster.category_rule_ids:
    #             if cat.categ_id == product_cat:
    #                     self.distribution_multiple = cat.qty_multiple;
    #                     return;

        
    #     else:
    #         for rule in reorder_rules:
    #             multiple_value = 1
                
    #             # Verificar diferentes campos donde puede estar el múltiplo
    #             if hasattr(rule, 'qty_multiple') and rule.qty_multiple > 0:
    #                 multiple_value = int(rule.qty_multiple)
    #             elif hasattr(rule, 'multiple_qty') and rule.multiple_qty > 0:
    #                 multiple_value = int(rule.multiple_qty)
    #             elif hasattr(rule, 'product_multiple') and rule.product_multiple > 0:
    #                 multiple_value = int(rule.product_multiple)
                
    #             if multiple_value > 1:
    #                 self.distribution_multiple = multiple_value
    #                 return
    
    def _are_required_modules_installed(self):
        """Verificar si los módulos requeridos están instalados"""
        required_modules = [
            'automatizacion_reglas_abastecimiento',  
            'setu_advance_reordering'   
        ]
        
        installed_modules = self.env['ir.module.module'].search([
            ('name', 'in', required_modules),
            ('state', '=', 'installed')
        ])
        
        installed_names = installed_modules.mapped('name')
        return len(installed_names) > 0  # Al menos uno de los módulos debe estar instalado

    

    @api.onchange('product_qty')
    def onChangeJustProductQty(self):
        pass

    @api.onchange('distribution_multiple')
    def onChangeJustDistributionMultiple(self):
        pass

    @api.onchange('product_id')
    def _onchange_product_id_crossdock(self):
        # Cargar múltiplo desde el producto
        if self.product_id:
            if hasattr(self.product_id, 'mutiplos_distribucion'):
                multiplo = self.product_id.mutiplos_distribucion
                if multiplo and multiplo > 0:
                    self.distribution_multiple = multiplo
                else:
                    self.distribution_multiple = 1
        
        # Aplicar configuraciones de crossdock
        self._apply_crossdock_defaults()

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
        for vals in vals_list:
            # Cargar distribution_multiple desde product_template si no está definido
            if 'distribution_multiple' not in vals and vals.get('product_id'):
                product = self.env['product.product'].browse(vals['product_id'])
                if hasattr(product, 'mutiplos_distribucion'):
                    if product.mutiplos_distribucion > 1:
                        vals['distribution_multiple'] = product.product_tmpl_id.mutiplos_distribucion
            
            if 'order_id' in vals:
                order = self.env['purchase.order'].browse(vals['order_id'])
                if order.crossdock_enabled:
                    if 'use_crossdock' not in vals:
                        vals['use_crossdock'] = True
                    
                    if 'line_crossdock_percentage' not in vals:
                        product_id = vals.get('product_id')
                        if product_id:
                            product = self.env['product.product'].browse(product_id)
                            if hasattr(product, 'crossdock_percentage') and product.crossdock_percentage:
                                vals['line_crossdock_percentage'] = product.crossdock_percentage / 100.0
                            else:
                                vals['line_crossdock_percentage'] = order.crossdock_percentage / 100.0
                        else:
                            vals['line_crossdock_percentage'] = order.crossdock_percentage / 100.0
        
        lines = super(PurchaseOrderLine, self).create(vals_list)
        
        return lines
    
    def _get_multiple_from_reorder_rules(self, product_id):
        """Obtener múltiplo desde las reglas de reabastecimiento de un producto"""
        if not self._are_required_modules_installed():
            return 1
        
        # Buscar reglas de reabastecimiento para este producto
        reorder_rules = self.env['stock.warehouse.orderpoint'].search([
            ('product_id', '=', product_id),
            ('active', '=', True)
        ])
        
        # Si hay múltiples reglas, tomar la primera con múltiplo definido
        for rule in reorder_rules:
            # Verificar diferentes campos donde puede estar el múltiplo
            if hasattr(rule, 'qty_multiple') and rule.qty_multiple > 0:
                return int(rule.qty_multiple)
            elif hasattr(rule, 'multiple_qty') and rule.multiple_qty > 0:
                return int(rule.multiple_qty)
            elif hasattr(rule, 'product_multiple') and rule.product_multiple > 0:
                return int(rule.product_multiple)
        
        return 1