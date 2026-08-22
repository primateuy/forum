# -*- coding: utf-8 -*-
{
    'name': 'FORUM - Extensión Advance Reordering',
    'version': '17.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Selección por categoría y grupo de almacenes, múltiplo de distribución y '
               'tipo de operación configurable en el reorder avanzado de Setu',
    'description': """
        Extiende setu_advance_reordering y setu_intercompany_transaction sin modificarlos.

        - Selección masiva de productos por categoría (y sus hijas) en el proceso de
          Reorder y en el wizard de creación/actualización de reglas.
        - Selección de almacenes destino por grupo de almacenes en el proceso de Reposición.
        - Respeto del múltiplo de distribución del producto (mutiplos_distribucion) en la
          demanda calculada, en la línea de orden de compra y en la transferencia
          inter-depósito, en vez de descubrir el incumplimiento al validar el picking.
        - Tipo de operación (stock.picking.type) configurable por canal ICT/IWT, con
          indicador de integración WMS.
    """,
    'author': 'Primate',
    'website': 'https://primateuy.odoo.com',
    'depends': [
        'setu_advance_reordering',
        'setu_intercompany_transaction',
        'automatic_crossdocking',
    ],
    'data': [
        'views/advance_reorder_orderprocess_views.xml',
        'views/advance_procurement_process_views.xml',
        'views/setu_interwarehouse_channel_views.xml',
        'views/setu_intercompany_channel_views.xml',
        'wizard/create_reordering_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
