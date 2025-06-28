# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Import Product Variants for Shop/E-Commerce',
    'version': '17.0.0.1',
    'category': 'Extra Tools',
    'summary': 'Shop product ECommerce product import product Variants and Attributes import Attributes import variant import product template import product from excel import product variants with Attributes import variants with Attributes update product shop data import',
    "price": 20,
    "currency": 'EUR',
    'description': """
            Import Product Variant on Odoo by Using excel/csv file,
            Import product with variants from XML file in odoo,
            Import product with variants from CSV file in odoo,
            Import Product with variants using custom field in odoo,
            Update product with variants from CSV or XML file in odoo,
            Update product by internal reference or code in odoo,
            Update product by barcode in odoo,
            Update product by name in odoo,

    """,
    'author': 'BROWSEINFO',
    'website': 'https://www.browseinfo.com/demo-request?app=import_product_variants&version=17&edition=Community',
    'depends': ['base','sale','account','website_sale','sale_management','stock','website'],
    'data': ['security/img_security.xml',
                'security/ir.model.access.csv',
            'wizard/product.xml',
            'wizard/product_custom_field.xml',
            'wizard/product_custom_tab.xml',
            "data/attachment_sample.xml"

             ],
	'qweb': [
		],
    'demo': [],
    'test': [],
    'license':'OPL-1',
    'installable': True,
    'auto_install': False,
    "live_test_url":'https://www.browseinfo.com/demo-request?app=import_product_variants&version=17&edition=Community',
    "images":["static/description/Banner.gif"],
}
