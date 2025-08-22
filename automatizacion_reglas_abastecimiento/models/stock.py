from odoo import fields, models


import logging
_logger = logging.getLogger(__name__);

class StockLocation(models.Model):
    _inherit = 'stock.location'

    automate_reordering = fields.Boolean(
        string='Participa en automatización',
        help="Habilita esta ubicación para reglas de reabastecimiento automático"
    )
    
    location_src_id = fields.Many2one(
        'stock.location',
        string='Ubicación de abastecimiento',
        domain="[('usage', '=', 'internal')]",
        help="Desde dónde se repondrá el stock (ej: centro logístico)"
    )
    
    default_min_qty = fields.Float(
        string='Cantidad mínima por defecto',
        default=0,
        help="Cantidad mínima para trigger de reabastecimiento"
    )
    
    default_max_qty = fields.Float(
        string='Cantidad máxima por defecto',
        default=0,
        help="Cantidad máxima para reposición"
    )

class StockRule(models.Model):
    _inherit = 'stock.rule';

    auto_generated = fields.Boolean(string="Generado Automáticamente", default=False)
    is_hierarchical = fields.Boolean(string="Regla Jerárquica", default=False)


class StockWareHouseGroup(models.Model):
    _inherit = 'stock.warehouse.group'

   
    category_rule_ids = fields.One2many(
            'warehouse.group.category.rule',
            'warehouse_group_id',
            string='Reglas por Categoría'
        )
    
    nivel_jerarquia_id = fields.Many2one(
        'niveles.jerarquia',
        string='Nivel de Jerarquía',
        ondelete='set null'
    )

    nivel_jerarquia_nombre = fields.Char(
        string="Nombre del Nivel",
        related='nivel_jerarquia_id.nombre',
        store=False
    )
    
