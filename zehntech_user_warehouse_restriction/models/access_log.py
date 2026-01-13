from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)

class WarehouseAccessLog(models.Model):
    _name = 'warehouse.access.log'
    _description = 'Warehouse Access Log'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    user_id = fields.Many2one(
        'res.users', 
        string="User", 
        required=True, 
        track_visibility='onchange',
        help='The user associated with this access log entry.'
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse', 
        string="Warehouse", 
        help='The warehouse associated with this log entry.'
    )
    action = fields.Selection(
        [('assign', 'Assign'), ('grant', 'Grant'), ('revoke', 'Revoke')], 
        string="Action",
        help='The action performed: "Assign" to allocate a warehouse, "Grant" to allow access, or "Revoke" to remove access.'
    )
    notes = fields.Text(
        'Notes',
        help='Additional information or notes about this access log entry.'
    )
    timestamp = fields.Datetime(
        'Timestamp', 
        default=fields.Datetime.now,
        help='The date and time when this log entry was created.'
    )
    active = fields.Boolean(
        'Active', 
        default=True,
        help='Indicates whether this log entry is active or archived.'
    )
    def unlink(self):
        """Archive log entries instead of deleting them."""
        for record in self:
            record.active = False
        return super(WarehouseAccessLog, self).unlink()