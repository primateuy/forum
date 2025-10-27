# -*- coding: utf-8 -*-
{
    'name': "Automatización Reglas de Abastecimiento",

    'summary': "Módulo para la automatización de las reglas de abastecimiento",

    'description': """
    """,

    'author': "Avance Software",
    'website': "https://avancesoftware.us/",

    'category': 'Uncategorized',
    'version': '0.1',

    'depends': ['base', 'product', 'stock',  'setu_intercompany_transaction', 'setu_advance_reordering'],

    'data': [
        'security/ir.model.access.csv',
        'views/views.xml',
        'views/templates.xml',
        'views/ProductView.xml',
        'views/StockView.xml',
        'views/WarehouseView.xml',
        'views/NivelesJerarquiaView.xml',
        'views/ProductTemplate.xml',
        'views/WizardView.xml'

    ],
    'demo': [
        'demo/demo.xml',
    ],
}

