# -*- coding: utf-8 -*-
{
    'name': "Purchase Requisition Product Matrix",
    'summary': "Matriz de variantes y subtotales en ordenes de compra abiertas.",
    'description': """
Extiende las ordenes de compra abiertas para permitir carga masiva por matriz
de variantes y mostrar subtotales/totales como en compras.
    """,
    'category': 'Inventory/Purchase',
    'version': '17.0.0.0',
    'depends': [
        'purchase_requisition',
        'purchase_product_matrix',
    ],
    'data': [
        'views/purchase_requisition_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'purchase_requisition_product_matrix/static/src/js/**/*',
        ],
    },
    'license': 'LGPL-3',
}
