from odoo import fields, models, api, _


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    warehouse_group_ids = fields.Many2many("stock.warehouse.group", string="Warehouse Group",
                                           help="Select one or more warehouse group, helps to grouping warehouses "
                                                "together for advance purchase process")
