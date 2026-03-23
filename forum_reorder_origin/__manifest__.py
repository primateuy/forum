{
    'name': 'FORUM - Optimización Reglas de Abastecimiento',
    'version': '17.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Agrega información de origen, sincroniza múltiplos y valida stock en reglas de reabastecimiento',
    'description': """
        - Columnas de stock en origen (a la mano, disponible, pronosticado) en reglas de reabastecimiento
        - Sincronización del múltiplo de distribución desde el producto a las reglas
        - Validación de stock disponible en origen al ejecutar reabastecimiento
        - Filtros de reglas cumplibles / no cumplibles
    """,
    'author': 'Primate',
    'website': 'https://primateuy.odoo.com',
    'depends': ['stock', 'product', 'automatic_crossdocking'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/reorder_warning_wizard_views.xml',
        'views/stock_orderpoint_views.xml',
        'views/product_template_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
