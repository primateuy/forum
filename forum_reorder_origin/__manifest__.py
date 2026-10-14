{
    'name': 'FORUM - Optimización Reglas de Abastecimiento',
    'version': '17.0.2.4.2',
    'category': 'Inventory/Inventory',
    'summary': 'Agrega información de origen, sincroniza múltiplos y valida stock en reglas de reabastecimiento',
    'description': """
        - Columnas de stock en origen (a la mano, disponible, pronosticado) en reglas de reabastecimiento
        - Sincronización del múltiplo de distribución desde el producto a las reglas
        - Validación de stock disponible en origen al ejecutar reabastecimiento
        - Filtros de reglas cumplibles / no cumplibles
        - La validación agrupa por (producto, almacén origen): las reglas que compiten por el
          mismo stock se evalúan en conjunto, no una por una
        - Columna de faltante en origen, totalizable en la lista
        - Wizard para repartir el stock insuficiente entre las reglas del mismo origen,
          reusando el motor de distribución de primate_reposicion_avanzada
        - El criterio de reparto se puede cambiar cuantas veces haga falta hasta ordenar:
          se guarda la demanda original y cada reparto se recalcula desde ahí
        - Acción para restaurar la demanda original y deshacer un reparto
        - Reposición en segundo plano: con muchas reglas, «Ordenar» crea un proceso (REP/…)
          que corre por tandas encadenadas por HTTP, sin cron, con avance en vivo; las reglas
          sin stock en origen se saltean y se listan
    """,
    'author': 'Primate',
    'website': 'https://primateuy.odoo.com',
    # primate_reposicion_avanzada se usa solo por el mixin de distribución
    # (primate.distribution.strategy.mixin): no hay acoplamiento con el resto del módulo.
    'depends': ['stock', 'product', 'automatic_crossdocking', 'primate_reposicion_avanzada', 'reorden_rendimiento', 'setu_advance_reordering'],
    'data': [
        'security/reposicion_proceso_security.xml',
        'security/ir.model.access.csv',
        'data/reposicion_proceso_data.xml',
        'wizard/reorder_warning_wizard_views.xml',
        'wizard/reorder_distribution_wizard_views.xml',
        'views/stock_orderpoint_views.xml',
        'views/product_template_views.xml',
        'views/reposicion_proceso_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'forum_reorder_origin/static/src/reposicion_progreso/reposicion_progreso.js',
            'forum_reorder_origin/static/src/reposicion_progreso/reposicion_progreso.xml',
            'forum_reorder_origin/static/src/orderpoint_list/orderpoint_list_controller.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
