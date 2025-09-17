# -*- coding: utf-8 -*-
{
    'name': "Account by Currency",

    'summary': """
        Change account on journal selection""",

    'description': """
        Configure one account for each currency in journals, then when
        you select a journal and a specific currency it will change the 
        receivable or payable account.
    """,

    'author': "Codex Development",
    'website': "http://www.perucodex.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Account',
    'version': '0.1',
    
    #Licence
    'license': 'LGPL-3',

    # any module necessary for this one to work correctly
    'depends': ['base', 'account'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'views/account_journal_views.xml',
        'views/account_payment_views.xml',
        'views/account_payment_register_views.xml',
    ],
    
    'images': ['static/description/banner.gif'],
}
