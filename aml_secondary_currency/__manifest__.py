# -*- coding: utf-8 -*-
{
    'name': 'Divisa Secundaria',
    'summary': 'Divisa secundaria en lineas de asiento',
    'description': 'Agrega Divisa secundaria en lineas de asiento.',
    'author': 'Proyecta',
    'website': 'https://odoo.proyectasoft.com',
    'category': 'Accounting/Accounting',
    'version': '17.0',
    'depends': ['base', 'account'],
    'data': [
        'views/account_move_line_view.xml',
        'wizard/compute_secondary_amount_view.xml',
        'security/security.xml',
    ]
}
