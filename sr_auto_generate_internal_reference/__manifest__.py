# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) Sitaram Solutions (<https://sitaramsolutions.in/>).
#
#    For Module Support : info@sitaramsolutions.in  or Skype : contact.hiren1188
#
##############################################################################

{
    'name': "Auto Generate Product SKU/Default Code/Internal Reference",
    'version': "17.0.0.0",
    'summary': "This modules helps you to generate internal code, SKU or Default code for products",
    'category': 'Products',
    'description': """
    product sku
    generate product sku manually
    generate product sku on create product
    on create product auto generate product sku code
    product default code
    generate product default code manually
    generate product default code on create product
    on create product generate default code for products
    product internal reference
    generate product internal reference manually
    generate product internal reference on create product
    on create product generate internal reference for products
    bulk generate product sku code manually
    bulk generate product default code manually
    bulk generate product internal code manually
    product variant sku generate manually
    product variant sku code generate on create product variant
    product variant internal reference generate manually
    product variant internal reference generate on create product variant
    product variant default code generate manually
    product variant default code generate on create product variant
    bulk generate product variant sku code manually
    bulk generate product variant default code manually
    bulk generate product variant Internal Reference manually
    generate sku with configurations
    generate internal reference with configurations
    generate default code with configurations
    """,
    'author': "Sitaram",
    'website':"www.sitaramsolutions.in",
    'depends': ['base', 'product','sale_management'],
    'data': [
        'data/sequence.xml',
        'security/ir.model.access.csv',
        # 'views/sr_inherit_res_config_setting.xml',
        'wizard/sr_inherit_res_config_setting.xml',
        'wizard/sr_manual_generate_sku.xml'
    ],
    'demo': [],
    "price": 10,
    "currency": 'EUR',
    "external_dependencies": {},
    "license": "OPL-1",
    'installable': True,
    'auto_install': False,
    'live_test_url':'https://youtu.be/N7e5pIC_QpU',
    'images': ['static/description/banner.png'],
}
