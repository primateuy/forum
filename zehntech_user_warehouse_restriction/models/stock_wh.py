from odoo import models, fields, api
from odoo.exceptions import AccessError
import logging

_logger = logging.getLogger(__name__)

class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    is_assigned = fields.Boolean(string="Is Assigned", default=False)
    help='Warehouses this user has access to. Only warehouses that are not already assigned to other users will be selectable.',

    @api.model
    def check_user_access(self, user_id, warehouse_id):
        """Check if the user has access to the specified warehouse."""
        user = self.env['res.users'].sudo().browse(user_id)
        warehouse = self.sudo().browse(warehouse_id)

        # Step 0: Check user groups for logging purposes
        is_admin_group = user.has_group('base.group_system')
        _logger.info("Admin group check for user %s: %s", user.name, is_admin_group)
        
        # Step 1: Validate warehouse access
        if warehouse not in user.allowed_warehouse_ids:
            _logger.info("Access denied for user %s attempting to access warehouse %s.", 
                         user.name, warehouse.name)
            raise AccessError(
                "Access Denied: You do not have permission to view this warehouse."
                " Please contact your administrator."
            )
        
        _logger.info("Access granted for user %s to warehouse %s.", user.name, warehouse.name)