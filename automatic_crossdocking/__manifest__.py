# -*- coding: utf-8 -*-


{
    'name': "Crossdocking Automático",

    'summary': "Módulo para generar crossdocking de automáticamente",

    'description': "Distribuir automáticamente parte de la mercadería comprada directamente a locales, al confirmar una Orden de Compra, utilizando reglas configurables de porcentaje, múltiplos, grupos de almacenes, y priorización. Permitir además la edición manual de toda la distribución antes de validar.",

    'author': "Avance Software",
    'website': "https://avancesoftware.us/",

    'category': 'Uncategorized',
    'version': '0.1',

    'depends': ['base', 'web','web_grid', 'purchase', 'purchase_stock', 'stock'],

    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'views/PurchaseOrderView.xml',
        'views/PurchaseOrderLineView.xml'
    ],
    
    "assets": {
        "web.assets_backend": [
            "automatic_crossdocking/static/src/components/welcome_component.js",
            "automatic_crossdocking/static/src/components/welcome_component.xml"
        
        ],
    },
    
    'demo': [
        'demo/demo.xml',
    ],
    
}

