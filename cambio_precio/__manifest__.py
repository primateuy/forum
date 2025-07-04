{
    "name": "Cambio de Lista de Precios",
    "version": "1.0",
    "depends": ["loyalty","point_of_sale", "sale_management"],
    "category": "Point of Sale",
    "summary": "Módulo para cambiar la lista de precios en el Punto de Venta",
    "description": """
    Este módulo permite cambiar la lista de precios en el Punto de Venta.
    """,
    "author": "Avance Software",
    "website": "https://www.avancesoftware.us",
    "data": [
        'views/views.xml',
    ],

    'icon': '/cambio_precio/static/description/icon.png',
    'license': 'LGPL-3',
    'assets': {
        'point_of_sale._assets_pos': [
            'cambio_precio/static/src/js/pricelistReward.js',
        ],
    },
    "installable": True,
    "auto_install": False,
}
