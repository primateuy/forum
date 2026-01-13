from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class ResUsers(models.Model):
    _inherit = 'res.users'

    allowed_warehouse_ids = fields.Many2many(
        'stock.warehouse',
        string='Warehouses',
        help='Warehouses this user has access to.',
        domain="[('is_assigned', '=', False)]",  
    )

    @api.model
    def create(self, vals):
        """
        Override create method to handle initial warehouse assignment and log the 'assign' action.
        Ensures only explicitly chosen warehouses are logged and assigned.
        """
        try:
            # Create the user first
            user = super(ResUsers, self).create(vals)

            # Check if warehouses are being assigned
            if 'allowed_warehouse_ids' in vals and vals['allowed_warehouse_ids']:
                # Extract warehouse IDs
                warehouse_ids = self._extract_warehouse_ids(vals['allowed_warehouse_ids'])
                _logger.debug(f"Extracted Warehouse IDs: {warehouse_ids}")

                # Process the explicitly chosen warehouses
                for warehouse_id in warehouse_ids:
                    if warehouse_id == 4:
                        # Skip warehouse ID 4 unless it's the only one
                        if len(warehouse_ids) > 1:
                            continue

                    # Log the 'assign' action for each valid warehouse
                    warehouse = self.env['stock.warehouse'].browse(warehouse_id)
                    warehouse.is_assigned = True  # Mark as assigned

                    if warehouse.exists():
                        self.env['warehouse.access.log'].create({
                            'user_id': user.id,
                            'warehouse_id': warehouse.id,
                            'action': 'assign',
                            'notes': f"Warehouse '{warehouse.name}' assigned to user '{user.name}'.",
                            'timestamp': fields.Datetime.now()
                        })
                        _logger.info(f"Logged warehouse '{warehouse.name}' (ID {warehouse.id}) for user '{user.name}'.")

            return user
        except Exception as e:
            _logger.error(f"Failed to create user with warehouses. Error: {e}")
            raise UserError("An error occurred while creating the user. Please check the logs for details.")

    def _extract_warehouse_ids(self, allowed_warehouse_vals):
        """
        Safely extract warehouse IDs from the allowed_warehouse_ids structure.
        Removes duplicates and ensures only valid IDs are returned.
        """
        try:
            if isinstance(allowed_warehouse_vals, list) and len(allowed_warehouse_vals) > 0:
                # Flatten and clean up warehouse IDs
                warehouse_ids = []
                for item in allowed_warehouse_vals:
                    if isinstance(item, list):  # Handle nested list
                        warehouse_ids.extend(item)
                    elif isinstance(item, int):  # Direct integer IDs
                        warehouse_ids.append(item)

                # Remove duplicates and ensure only valid IDs
                cleaned_warehouse_ids = list(set(warehouse_ids))

                # Log cleaned IDs for debugging
                _logger.debug(f"Cleaned Warehouse IDs: {cleaned_warehouse_ids}")
                return cleaned_warehouse_ids
            return []
        except Exception as e:
            _logger.error(f"Error extracting warehouse IDs: {e}")
            raise UserError("Error extracting warehouse IDs. Please check the logs for details.")

    def write(self, vals):
        """
        Override write method to handle:
        - 'grant' for newly assigned warehouses.
        - 'revoke' for removed warehouses.
        - Log reassignment of previously revoked warehouses.
        """
        try:
            old_warehouses = {user.id: set(user.allowed_warehouse_ids.ids) for user in self}
            result = super(ResUsers, self).write(vals)

            if 'allowed_warehouse_ids' in vals:
                for user in self:
                    new_warehouses = set(user.allowed_warehouse_ids.ids)
                    old_warehouse_ids = old_warehouses[user.id]

                    granted_warehouses = new_warehouses - old_warehouse_ids
                    revoked_warehouses = old_warehouse_ids - new_warehouses

                    # Handle 'Grant' logs (including re-granting previously revoked warehouses)
                    for warehouse_id in granted_warehouses:
                        warehouse = self.env['stock.warehouse'].browse(warehouse_id)
                        warehouse.is_assigned = True  # Mark as assigned

                        # Log grant for all newly assigned warehouses
                        self.env['warehouse.access.log'].create({
                            'user_id': user.id,
                            'warehouse_id': warehouse.id,
                            'action': 'grant',
                            'notes': f"Warehouse '{warehouse.name}' granted to user '{user.name}'.",
                            'timestamp': fields.Datetime.now(),
                        })
                        _logger.info(f"Logged grant for warehouse '{warehouse.name}' to user '{user.name}'.")

                    # Handle 'Revoke' logs
                    for warehouse_id in revoked_warehouses:
                        warehouse = self.env['stock.warehouse'].browse(warehouse_id)
                        warehouse.is_assigned = False  # Mark as unassigned

                        # Log revoke for all removed warehouses
                        self.env['warehouse.access.log'].create({
                            'user_id': user.id,
                            'warehouse_id': warehouse.id,
                            'action': 'revoke',
                            'notes': f"Warehouse '{warehouse.name}' revoked from user '{user.name}'.",
                            'timestamp': fields.Datetime.now(),
                        })
                        _logger.info(f"Logged revoke for warehouse '{warehouse.name}' from user '{user.name}'.")

            return result
        except Exception as e:
            _logger.error(f"Error in write method. Exception: {e}")
            raise UserError("An error occurred while updating warehouse access. Please check the logs.")


    def set_warehouse_access(self, user_id, warehouse_ids):
        """
        Assign or update warehouse access for a specific user.
        Removes warehouse with ID 4 by default and creates log entries.
        """
        try:
            user = self.browse(user_id)
            if not user:
                raise UserError("User not found.")

            # Ensure no warehouse is already assigned
            new_warehouses = self.env['stock.warehouse'].browse(warehouse_ids)
            warehouse.is_assigned = True  # Mark as assigned

            for warehouse in new_warehouses:
                if warehouse.is_assigned and warehouse.id not in user.allowed_warehouse_ids.ids:
                    raise UserError(f"Warehouse '{warehouse.name}' is already assigned to another user.")

            # Remove warehouse with ID 4 by default
            if 4 in warehouse_ids:
                warehouse_ids.remove(4)
                _logger.info(f"Removed warehouse with ID 4 from the assignment for user '{user.name}'.")

            # Assign warehouses
            user.allowed_warehouse_ids = [(6, 0, warehouse_ids)]

            # Log access grant
            for warehouse in new_warehouses:
                warehouse.is_assigned = True
                self.env['warehouse.access.log'].create({
                    'user_id': user.id,
                    'warehouse_id': warehouse.id,
                    'action': 'grant',
                    'notes': f"Access granted to warehouse '{warehouse.name}' for user '{user.name}'."
                })
                _logger.info(f"Logged grant access for warehouse '{warehouse.name}' to user '{user.name}'.")

        except Exception as e:
            _logger.error(f"Error in set_warehouse_access method. Exception: {e}")
            raise UserError("An error occurred while setting warehouse access. Please check the logs.")
