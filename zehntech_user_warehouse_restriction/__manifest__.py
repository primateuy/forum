{
    'name': 'User Warehouse Restriction',
    "version": '17.0.1.0.0',
    'category': 'Inventory',
    'summary': """Enhance warehouse security with user-specific restrictions. This User Warehouse   Restriction App Odoo App improves inventory management by allowing administrators to set warehouse access permissions for specific users. By ensuring that only authorized personnel can access certain warehouses, it enhances data security and operational control..""",
    'description': """ The User Warehouse Restriction module enhances inventory management by enabling warehouse restrictions for specific users. Administrators can configure user permissions to ensure access only to authorized warehouses, improving data security and operational control. """,
    "author": "Zehntech Technologies Inc.",
    "company": "Zehntech Technologies Inc.",
    "maintainer": "Zehntech Technologies Inc.",
    "contributor": "Zehntech Technologies Inc.",
    "website": "https://www.zehntech.com/",
    "support": "odoo-support@zehntech.com",
    'depends': ['stock','mail'],
    'data': [
            'security/ir.model.access.csv',
            'security/warehouse_access_log_security.xml',
            'security/user_warehouse_rules.xml',
            'security/manager_group.xml',
            'views/res_users_views.xml',
            'data/demo_user.xml',
            'views/warehouse_menu_item.xml',      
            'views/warehouse_access_log_views.xml', 
    ],
    "images": [
        "static/description/banner.png",
    ],
    'i18n': [
        'i18n/de_CH.po',    # German translation file
        'i18n/es.po',      # Spanish translation file
        'i18n/fr.po',   # French translation file
        'i18n/ja_JP.po',   # Japanese translation file
    ],
    "license": "OPL-1",
    'installable': True,
    'application': True,
    'auto_install': False,
    'price': 0.00,
    'currency': 'USD'
}
