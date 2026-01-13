from odoo import models, fields, api, _
from odoo.exceptions import UserError


class StockWarehouse(models.Model):
    _inherit = "stock.warehouse"

    def write(self, vals):
        if self.env.user.has_group('eg_warehouse_edit_restriction.stock_warehouse_edit_restriction'):
            raise UserError(_("You don't have access to edit Warehouse."))
        else:
            return super(StockWarehouse, self).write(vals)
