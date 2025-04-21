# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'Inter Company Transfer',
    'version': '1.6',
    'price': 149,
    'currency': 'EUR',
    'category': 'stock',
    'summary': """
        Inter Company Transfer / Inter Warehouse Transfer
        This app is used to keep track of all the transactions between two warehouses, source warehouse
        and destination warehouse can be of same company and can be of different company.
        
        -Intercompany transaction (transaction between warehouses of two different companies)
        -Interwarehouse transaction (transaction between warehouses of same company)
        -Reverse transactions / Reverse transfer (Inter company transaction or Inter warehouse transaction)
        
        -Define inter company rules which will create inter comapny transactions record automatically
        -Create intercompany transaction automatically when any sales order validated in the company
        -Create interwarehouse transaction automatically when any sales order validated in the company
	-stock manage, inventory management techniques, internal transfer, coverage,
	ict, twt, 
    """,
    'website': 'http://www.setuconsulting.com',
    'support': 'support@setuconsulting.com',
    'description': """
        Intercompany Transfer
        ==========================================================
        This app is used to keep track of all the transactions between two warehouses, source warehouse
        and destination warehouse can be of same company and can be of different company.
        
        This app will perform following operations.
        -> Inter company transaction (transaction between warehouses of two different companies)
        -> Inter warehouse transaction (transaction between warehouses of same company)
        -> Reverse transactions (Inter company or Inter warehouse)
        
        Advance features
        -> Define inter company rules which will create inter comapny transactions record automatically
        -> Create intercompany transaction automatically when any sales order validated in the company
        -> Create interwarehouse transaction automatically when any sales order validated in the company
    """,
    'author': 'Setu Consulting Services Pvt. Ltd.',
    'license': 'OPL-1',
    'sequence': 19,
    'images': ['static/description/banner.gif'],
    'depends': ['sale_management', 'purchase_stock', 'sale_stock'],
    'data': [
        'data/data.xml',
        'views/setu_ict_auto_workflow.xml',
        'views/setu_intercompany_channel.xml',
        'views/setu_interwarehouse_channel.xml',
        'views/setu_intercompany_transfer.xml',
        'views/setu_interwarehouse_transfer.xml',
        'views/setu_reverse_transfer.xml',
        'views/res_company.xml',
        'views/ict_sale_order_form.xml',
        'views/ict_purchase_order_form.xml',
        'views/ict_stock_picking_form.xml',
        'views/ict_account_invoice_form.xml',
        'wizard/wizard_import_ict_products.xml',
        'security/ir.model.access.csv',
    ],
    'application': True,
    # 'pre_init_hook': 'pre_init',
    'live_test_url': 'https://www.youtube.com/watch?v=SUDr7uA83uk&list=PLH6xCEY0yCID5xMUPKh_818Dq6Fpq6rg8',
}
