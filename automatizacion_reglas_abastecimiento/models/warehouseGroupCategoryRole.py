
from odoo import fields, api, models



class WarehouseGroupCategoryRule(models.Model):
    _name = 'warehouse.group.category.rule'
    _description = 'Reglas de abastecimiento por categoría y grupo'

    warehouse_group_id = fields.Many2one(
        'stock.warehouse.group', string='Grupo de Almacenes', required=True, ondelete='cascade'
    )
    categ_id = fields.Many2one(
        'product.category', string='Categoría de Producto', required=True
    )
    min_qty = fields.Float(string='Cantidad mínima sugerida', required=True)
    max_qty = fields.Float(string='Cantidad máxima sugerida', required=True)
    use_multiples = fields.Boolean(string='Usar múltiplos')
    qty_multiple = fields.Float(string='Múltiplo', default=1)
