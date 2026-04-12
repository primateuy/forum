{
    "name": "POS Sale Order Sync - Auto Invoice",
    "version": "17.0.1.0.0",
    "category": "Point of Sale",
    "author": "PrimateUY",
    "summary": "Facturación manual por límite de líneas del punto de emisión",
    "description": """
        Agrega una acción en la vista lista de órdenes de venta que permite
        seleccionar un grupo de órdenes y generar una factura en borrador
        respetando el límite de líneas del punto de emisión configurado en
        el tipo de pedido. Las órdenes que superan el límite quedan fuera
        y se informa al usuario cuántas líneas y órdenes quedaron pendientes.
    """,
    "depends": ["pos_sale_order_sync"],
    "data": [
        "security/ir.model.access.csv",
        "views/sale_autoinvoice_wizard_view.xml",
    ],
    "installable": True,
    "application": False,
}
