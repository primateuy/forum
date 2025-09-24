from odoo import models, fields, api
from odoo.exceptions import ValidationError



class ProductProduct(models.Model):
    _inherit = 'product.product'
    
    warehouse_group_id = fields.Many2one(
        'stock.warehouse.group',
        string="Grupo de Almacenes",
        help="Define a qué grupo de almacenes pertenece esta variante",
    )

    
    
    def generarReglasAbastecimiento(self):
        for product in self:

            if not product.warehouse_group_id:
                continue
                
            grupos = []
            if product.warehouse_group_id.nivel_jerarquia_id: 
                grupos = product.env['stock.warehouse.group'].search([
                    ('nivel_jerarquia_id.seq', '<=', product.warehouse_group_id.nivel_jerarquia_id.seq)
                ])
            else:
                grupos.append(product.warehouse_group_id)

            existing_rules = product.env['stock.warehouse.orderpoint'].search([
                ('product_id', '=', product.id),
                ('company_id', '=', product.env.company.id)
            ])
            if existing_rules:
                existing_rules.unlink()

            categoriaProducto = product.categ_id
            for grupo in grupos:
                almacenes = grupo.warehouse_ids
                
                categoriaGrupo = False
                for cat in grupo.category_rule_ids:
                    if cat.categ_id.id == categoriaProducto.id:
                        categoriaGrupo = cat
                        break
                
                for almacen in almacenes:
                    ubicaciones_internas = product.env['stock.location'].search([
                        ('usage', '=', 'internal'),
                        ('id', 'child_of', almacen.view_location_id.id),
                        ('replenish_location', '=', True),
                        ('automate_reordering', '=', True)
                    ])

                    for ubicacion in ubicaciones_internas:
                        if categoriaGrupo and categoriaGrupo.use_multiples and categoriaGrupo.qty_multiple <= 0:
                            raise ValidationError("Se encontró la categoría pero la misma tiene un múltiplo menor o igual a 0")

                        product.env['stock.warehouse.orderpoint'].create({
                            'product_id': product.id,
                            'location_id': ubicacion.id,
                            'warehouse_id': almacen.id,
                            'product_min_qty': categoriaGrupo.min_qty if categoriaGrupo and categoriaGrupo.min_qty else ubicacion.default_min_qty,
                            'product_max_qty': categoriaGrupo.max_qty if categoriaGrupo and categoriaGrupo.max_qty else ubicacion.default_max_qty,
                            'qty_multiple': categoriaGrupo.qty_multiple if categoriaGrupo and categoriaGrupo.use_multiples else 1,
                            'company_id': product.env.company.id
                        })

    def write(self, vals):
        res = super(ProductProduct, self).write(vals)

        if 'warehouse_group_id' in vals or 'categ_id' in vals:
            self.generarReglasAbastecimiento()
                
        return res;

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    warehouse_group_id = fields.Many2one(
        'stock.warehouse.group',
        string="Grupo de Almacenes",
        help="Define a qué grupo de almacenes pertenece esta variante",
    )


    def generarReglasAbastecimiento(self):
        if self.product_variant_ids:
            self.product_variant_ids.with_context(skip_auto_rules=True).generarReglasAbastecimiento()
            
         
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Reglas Generadas',
                'message': f'Se generaron reglas para {len(self.product_variant_ids)} variantes',
                'type': 'success',
                'sticky': False,
            }
        }

    def write(self, vals):
            res = super(ProductTemplate, self).write(vals)
            
            if 'warehouse_group_id' in vals and not self._context.get('skip_auto_rules'):
                self.product_variant_ids.with_context(skip_auto_rules=True).write({
                    'warehouse_group_id': self.warehouse_group_id.id,
                })
                

                for variante in self.product_variant_ids:
                    variante.generarReglasAbastecimiento()
                
                
                
            return res

    @api.model
    def create(self, vals):
        template = super(ProductTemplate, self).create(vals)
        
        if 'warehouse_group_id' in vals:
            template.product_variant_ids.with_context(skip_auto_rules=True).write({
                'warehouse_group_id': template.warehouse_group_id.id,
            })
            
            template.product_variant_ids.generarReglasAbastecimiento()

        return template