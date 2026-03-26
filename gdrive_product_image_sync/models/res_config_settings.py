from odoo import fields, models


class ResConfigSettings(models.TransientModel):

    _inherit = 'res.config.settings'

    gdrive_folder_id = fields.Char(
        string='Google Drive Folder ID',
        config_parameter='gdrive_product_image_sync.folder_id',
    )
    gdrive_service_account_json = fields.Char(
        string='Service Account JSON',
        config_parameter='gdrive_product_image_sync.service_account_json',
    )
    gdrive_sync_interval = fields.Integer(
        string='Sync Interval (minutes)',
        default=5,
        config_parameter='gdrive_product_image_sync.sync_interval',
    )
