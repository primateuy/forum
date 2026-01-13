from odoo import api, fields, models


class InheritedWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    boolean_warehouse_flag = fields.Boolean(string='Boolean Flag',default=False)

