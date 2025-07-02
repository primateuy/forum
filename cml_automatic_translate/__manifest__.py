# -*- coding: utf-8 -*-
{
    'name': 'Automatic Translate Export file PO',
    'version': '1.0.0',
    'summary': 'Translates modules and models automatically using google translator.',
    'author': 'CML',
    'website': 'kaypi.pe',
    'category': 'tools',
    'depends': ['base'],
    'external_dependencies': {
        'python': ['polib', 'deep-translator'],
    },
    "data": [
        "wizard/base_language_export_views.xml",
    ],
    'images': ["static/description/banner.png"],
    'application': True,
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
