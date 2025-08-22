from odoo import api, fields, models




class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    group_location_ids = fields.One2many(
        'warehouse.group.location',
        'warehouse_id', 
        string='Ubicaciones por Grupo'
    )


class WarehouseGroupLocation(models.Model):
    _name = 'warehouse.group.location'
    _description = 'Ubicaciones por Grupo en Almacén'

    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Almacén',
        required=True,
        ondelete='cascade'
    )
    group_id = fields.Many2one(
        'stock.warehouse.group',
        string='Grupo de Almacenes',
        required=True
    )
    location_id = fields.Many2one(
        'stock.location',
        string='Ubicación Designada',
        required=True,
        domain="[('usage', '=', 'internal')]"
    )

    default_min_qty = fields.Float(string='Cantidad mínima default', required=True)
    default_max_qty = fields.Float(string='Cantidad máxima default', required=True)

    automate_reordering = fields.Boolean(string="Reabastecimiento aútomatico", default=False);

    _sql_constraints = [
        ('warehouse_group_unique',
         'UNIQUE(warehouse_id, group_id)',
         'Ya existe una configuración para este grupo en el almacén'),
    ]