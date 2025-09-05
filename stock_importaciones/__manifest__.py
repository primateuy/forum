{
    'name': 'Distinción de Operaciones de Importación',
    'description': 'Permite facilitar la gestión de las Operaciones de Importación.',
    'author': 'Matías Mastrángelo',
    'depends': ['base', 'stock', 'stock_landed_costs'],
    'application': True,
    'post_init_hook': '_post_init_hook',
    'data' : [
            'security/close_transfers_landed_costs.xml',
            'views/stock_picking_type_view.xml',
            'views/stock_picking_view.xml',
            'views/stock_landed_cost_views.xml',
            ],
}