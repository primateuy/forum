{
    'name': 'Google Drive Product Image Sync',
    'version': '17.0.1.0.0',
    'category': 'Inventory/Products',
    'summary': 'Sync product images from Google Drive folder by SKU',
    'author': 'Primate',
    'website': '',
    'license': 'LGPL-3',
    'depends': [
        'product',
        'website_sale',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/gdrive_sync_log_views.xml',
        'views/product_product_views.xml',
        'data/ir_cron_data.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
