# -*- coding: utf-8 -*-
###############################################################################
# Author      : Varanval IT Solutions
# Copyright   : (c) 2025 Varanval IT Solutions. All Rights Reserved.
#
# This software and associated files are the copyrighted property of Varanval IT Solutions.
# Unauthorized copying, redistribution, or modification of any part of this code
# is strictly prohibited unless expressly permitted by the author.
#
# This module is a paid product. It is licensed for use only by the customer
# who has purchased it, and only for the number of users specified at purchase.
#
# For licensing inquiries, contact: support@weblyticlabs.com
###############################################################################
{
    'name': 'POS Hide/Show Invoice Button',
    'version': '17.1.1',
    'category': 'Point of Sale',
    'sequence': 1,
    'summary': "POS hide invoice button | POS show invoice button | Restrict invoice button in POS | Hide or show invoice in Odoo POS | Odoo POS invoice button control | Invoice button visibility in POS | POS invoicing access control | Hide invoice option POS payment screen | Show/hide invoice button POS | Manage invoice button Odoo POS",
    'description': """Easily control the visibility of the invoice button on the POS payment screen in Odoo. 
            Enable or disable the Hide Invoice Button feature from POS settings to instantly hide or show the invoice button as per your business needs. 
            This module helps prevent unauthorized invoicing, keeps the POS interface clean, and improves cashier efficiency. 
            Perfect for retail, restaurant, and multi-store environments where role-based invoicing control is essential. 
            Seamless integration with Odoo 18 POS, no technical skills required — configure in seconds and apply changes instantly in the next POS session.""",
    'depends': ['base', 'point_of_sale', 'stock'],
    'keywords': [
        'pos',
        'hide invoice button',
        'show invoice button',
        'restrict invoice button',
        'odoo pos invoice control',
        'invoice button visibility',
        'hide or show invoice',
        'pos invoicing control',
        'pos payment screen customization',
        'invoice button access control',
        'pos hide invoice',
        'pos show invoice',
        'odoo pos customization',
        'point of sale invoice button',
        'manage invoice button pos',
        'pos interface control',
        'pos workflow customization',
        'odoo pos',
        'odoo',
        'POS Hide Invoice Button',
        'POS Hide Invoice',
        ' POS Restrict Invoice'
    ],
    'author': 'Varanval IT Solutions',
    'company': 'Varanval IT Solutions',
    'price': '3.00',
    'currency': 'USD',
    'data': [
        'views/res_config_settings.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'vits_hide_invoice_button_pos/static/src/xml/inherit_payment_screen.xml',
        ],
    },
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'OPL-1',
}
