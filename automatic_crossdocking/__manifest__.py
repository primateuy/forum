# -*- coding: utf-8 -*-
{
    'name': "Crossdocking Automático",

    'summary': "Módulo para generar crossdocking de automáticamente",

    'description': "Distribuir automáticamente parte de la mercadería comprada directamente a locales, al confirmar una Orden de Compra, utilizando reglas configurables de porcentaje, múltiplos, grupos de almacenes, y priorización. Permitir además la edición manual de toda la distribución antes de validar.",

    'author': "Avance Software",
    'website': "https://avancesoftware.us/",

    'category': 'Uncategorized',
    'version': '0.1',

    'depends': ['base', 'purchase', 'stock'],

    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'views/PurchaseOrderView.xml',
        'views/PurchaseOrderLineView.xml',
        
        'views/CrossDockWizardView.xml'
    ],
    'demo': [
        'demo/demo.xml',
    ],
}

