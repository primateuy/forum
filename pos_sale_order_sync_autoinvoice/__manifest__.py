{
    "name": "POS Sale Order Sync - Auto Invoice",
    "version": "17.0.0.0",
    "category": "Point of Sale",
    "author": "PrimateUY",
    "summary": "Automatic draft invoice generation when sale order lines exceed the punto de emision limit",
    "depends": ["pos_sale_order_sync"],
    "data": [
        "views/pos_config_view.xml",
    ],
    "installable": True,
    "application": False,
}
