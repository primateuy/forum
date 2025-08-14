from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

class ProductProduct(models.Model):
    _inherit = 'product.product'
    
    warehouse_group_id = fields.Many2one(
        'stock.warehouse.group',
        string="Grupo de Almacenes",
        help="Define a qué grupo de almacenes pertenece esta variante",
        
    )

    def generarReglasAbastecimiento(self):
        if not self.warehouse_group_id:
            return;
    
    

        
        current_level = self.warehouse_group_id.warehouse_group_level

        grupos = self.env['stock.warehouse.group'].search([
            ('warehouse_group_level', '<=', current_level)
        ])
        StockRule = self.env['stock.warehouse.orderpoint']

        existing_rules = StockRule.search([
        ('product_id', '=', self.id),
        ('company_id', '=', self.env.company.id)
        ])
        
        if existing_rules:
            existing_rules.unlink()
        


        
        categoriaProducto = self.categ_id;

        for grupo in grupos:
            almacenes = grupo.warehouse_ids;
            
            categoriaGrupo = False;

            for cat in grupo.category_rule_ids:
                if cat.categ_id.id == categoriaProducto.id:
                    categoriaGrupo = cat;
                break;
            
            for almacen in almacenes:
                ubicaciones_internas = self.env['stock.location'].search([
                    ('usage', '=', 'internal'),
                    ('id', 'child_of', almacen.view_location_id.id),
                    ('replenish_location', '=', True),
                    ('automate_reordering', '=', True)
                ]);

                
                for ubicacion in ubicaciones_internas:
                   

                   if categoriaGrupo and categoriaGrupo.use_multiples and categoriaGrupo.qty_multiple <= 0:
                       raise ValidationError("Se econtró la categoría pero la misma tiene un multiplo menor o igual a 0")



                   
                    
                   StockRule.create({
                        'product_id': self.id,
                        'location_id': ubicacion.id,
                        'warehouse_id': almacen.id,
                        'product_min_qty': categoriaGrupo.min_qty if categoriaGrupo and categoriaGrupo.min_qty else ubicacion.default_min_qty,
                        'product_max_qty': categoriaGrupo.max_qty if categoriaGrupo and categoriaGrupo.max_qty else ubicacion.default_max_qty,
                        'qty_multiple': categoriaGrupo.qty_multiple if categoriaGrupo and categoriaGrupo.use_multiples else 1,
                        'company_id': self.env.company.id
                    })
    @api.model
    def write(self, vals):


        res = super(ProductProduct, self).write(vals);

        if 'warehouse_group_id' in vals or 'categ_id' in vals:
            self.generarReglasAbastecimiento();
        
        return res;

