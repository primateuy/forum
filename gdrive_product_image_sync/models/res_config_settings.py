from odoo import fields, models


class ResConfigSettings(models.TransientModel):

    _inherit = 'res.config.settings'

    gdrive_folder_id = fields.Char(
        string='Carpeta de Fotos Nuevas (ID)',
        config_parameter='gdrive_product_image_sync.folder_id',
    )
    gdrive_processed_folder_id = fields.Char(
        string='Carpeta de Fotos Procesadas (ID)',
        config_parameter='gdrive_product_image_sync.processed_folder_id',
    )
    gdrive_move_after_sync = fields.Boolean(
        string='Mover imágenes después de sincronizar',
        config_parameter='gdrive_product_image_sync.move_after_sync',
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
    gdrive_batch_size = fields.Integer(
        string='Batch Size',
        default=10,
        config_parameter='gdrive_product_image_sync.batch_size',
    )
