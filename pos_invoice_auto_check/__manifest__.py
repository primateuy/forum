# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.

{
    "name" : "POS Invoice Auto Check in odoo",
    "version" : "17.0.0.1",
    "category" : "Point of Sale",
    "depends" : ['base','sale','point_of_sale'],
    "author": "BROWSEINFO",
    'summary': 'App point of sales auto invoice check pos Auto Invoice Reconcile pos invoice auto generation pos invoice automation POS Invoice Automate point of sales invoice auto check pos invoice auto check pos invoice check pos automation invoice on pos invoice check',
    "price": 15,
    "currency": 'EUR',
    "description": """
    BrowseInfo developed a new odoo/OpenERP module apps. 
    Odoo point of sales invoice auto check auto invoice check in point of sales auto invoice check POS
    auto invoice pos pos accounting invoice After Click on Payment Button Invoice Button Auto check automatically.
    Auto invoice from POS Auto invoice from Point of Sale Autocheck invoice button on POS.
    pos Auto invoice validate pos Auto invoice validate POS auto invoice check button POS Odoo 
    Odoo pos auto invoice check button POS Odoo POS auto invoice checked button pos

    Point of Sale Auto invoice validate Point of Sale Auto invoice validate Point of Sale auto invoice check button Point of Sale Odoo 
    Odoo Point of Sale auto invoice check button Point of Sale Odoo Point of Sale auto invoice checked button Point of Sale


    Point of Sales Auto invoice validate Point of Sales Auto invoice validate Point of Sales auto invoice check button Point of Sales Odoo 
    Odoo Point of Sales auto invoice check button Point of Sales Odoo Point of Sales auto invoice checked button Point of Sales

    """,
    "website" : "https://www.browseinfo.com/demo-request?app=pos_invoice_auto_check&version=17&edition=Community",
    "data": [
        'data/mail_cron.xml',
        'views/custom_pos_view.xml',
        
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_invoice_auto_check/static/src/app/pos_invoice_auto_check.js',
        ],
    },



    "license": "OPL-1",
    "auto_install": False,
    "installable": True,
    "live_test_url":'https://www.browseinfo.com/demo-request?app=pos_invoice_auto_check&version=17&edition=Community',
    "images":['static/description/Banner.gif'],
}
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
