{
    'name': 'FORUM - Optimización Reglas de Abastecimiento',
    'version': '17.0.2.2.0',
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
    """,
    'author': 'Primate',
    'website': 'https://primateuy.odoo.com',
    # primate_reposicion_avanzada se usa solo por el mixin de distribución
    # (primate.distribution.strategy.mixin): no hay acoplamiento con el resto del módulo.
    'depends': ['stock', 'product', 'automatic_crossdocking', 'primate_reposicion_avanzada'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/reorder_warning_wizard_views.xml',
        'wizard/reorder_distribution_wizard_views.xml',
        'views/stock_orderpoint_views.xml',
        'views/product_template_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
