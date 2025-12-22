# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.

{
    "name": "Advance POS View - POS Product Switch View and Sort View",
    "version": "17.0.0.0",
    "category": "Point of Sale",
    'summary': 'POS product advance view POS product switch view POS product list view pos product sorting point of dale product switch view point of sale product list view point of sale product sorting pos product sort view point of sale product sort pos advance view',
    "description": """

             POS Product Switch View and Sort in odoo,
             POS Product in Grid View,
             POS Product in List View,
             POS Product Sort by Name,
             POS Product Sort by Code,
             POS Product Sort by UOM,
             POS Product Sort by Sale Price,
             POS Product Sort by Avalilable Qty,

    """,
    "author": "BROWSEINFO",
    'website': "https://www.browseinfo.com/demo-request?app=bi_pos_product_list_view&version=17&edition=Community",
    "price": 15,
    "currency": 'EUR',
    "depends": ['point_of_sale'],
    "data": [
        'views/pos_config_view.xml',
    ],

    'assets': {
        'point_of_sale._assets_pos': [
            'bi_pos_product_list_view/static/src/css/pos.css',
            'bi_pos_product_list_view/static/src/js/pos_product_list_view.js',    
            'bi_pos_product_list_view/static/src/xml/pos_product_list_view.xml',
        ],
    },
    
    "license": "OPL-1",
    "auto_install": False,
    "installable": True,
    'live_test_url': 'https://www.browseinfo.com/demo-request?app=bi_pos_product_list_view&version=17&edition=Community',
    "images": ["static/description/Banner.gif"],
}
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
