{
    "name": "POS Sale Order Sync",
    "version": "17.0.0.0",
    "category": "Point of Sale",
    "author": "PrimateUY",
    "summary": "Create Sale Orders from POS Orders",
    "depends": ["point_of_sale", "sale", 'purchase', 'stock', 'sale_order_type', 'sale_purchase_inter_company_rules', 'l10n_uy_einvoice_base', 'account'],
    "data": [
        'views/pos_config_view.xml',
        'views/product_template_stock_tab.xml',
        'views/sale_order_view.xml',
        'views/crear_factura_view.xml',
        'views/punto_emision_view.xml'
    ],
    "installable": True,
    "application": False,
}
