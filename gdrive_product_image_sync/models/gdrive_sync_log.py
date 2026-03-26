from odoo import fields, models


class GDriveSyncLog(models.Model):
    _name = "gdrive.sync.log"
    _description = "Google Drive Sync Log"
    _order = "sync_date desc"

    name = fields.Char(string="Filename", required=True)
    sku = fields.Char(string="SKU")
    status = fields.Selection(
        [
            ("ok", "OK"),
            ("warning", "Warning"),
            ("error", "Error"),
        ],
        string="Status",
        required=True,
    )
    message = fields.Text(string="Message")
    sync_date = fields.Datetime(
        string="Sync Date",
        default=fields.Datetime.now,
        required=True,
    )
