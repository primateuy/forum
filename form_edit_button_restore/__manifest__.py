# -*- coding: utf-8 -*-
{
    'name': 'Form Edit Button Restore | Edit/Save Workflow | Edit button',
    'version': '17.0.0.0.0',
    'summary': 'Restore Edit/Save workflow in form views like Odoo 13',
    'description': '''
        This module restores the classic Edit/Save workflow in Odoo 18 form views:
        - Form views open in read-only mode by default.
        - An Edit button is shown; Save and Discard are hidden.
        - Clicking Edit switches to edit mode, showing Save and Discard buttons.
        - After saving or discarding, the form returns to read-only mode.
        - Works globally for all form views.
        Perfect for users who prefer the classic Odoo workflow!
        Support & Documentation:
        - Email: prt.c.bhatti@gmail.com
        Compatible with: Odoo 18 Community
    ''',
    'category': 'User Interface',
    'author': "Preet Bhatti",
    'website': "https://preetbhatti.github.io/portfolio/",
    'license': 'OPL-1',
    'depends': ['web'],
    'assets': {
        'web.assets_backend': [
            'form_edit_button_restore/static/src/**/*',
        ],
    },
    'images': ['static/description/banner.gif'],
    'installable': True,
    'application': True,
    'auto_install': False,
}
