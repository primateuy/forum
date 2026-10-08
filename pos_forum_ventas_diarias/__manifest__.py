# -*- coding: utf-8 -*-
{
    'name': 'FORUM — Ventas del POS por forma de pago',
    'version': '17.0.1.1.0',
    'author': 'PRIMATE',
    'website': 'https://primate.uy',
    'category': 'Point of Sale',
    'license': 'LGPL-3',
    'summary': """
        Consulta detallada de los pagos del punto de venta, agrupable por forma
        de pago, local, sesión, cajero y fecha, con acceso a la transacción de
        pago del adquirente.
        """,
    'description': """
Extiende la vista nativa de Pagos del punto de venta para que las sucursales
puedan consultar su venta diaria abierta por forma de pago.

Agrega a pos.payment los campos necesarios para agrupar (local y cajero), una
vista de lista con totales, una vista dinámica para el cruce forma de pago por
día, y filtros de fecha de uso corriente.

El acceso se controla con un grupo propio y una regla que limita lo que ve cada
usuario a los puntos de venta que tiene asignados.
    """,
    'depends': [
        'point_of_sale',
        'odoo_pos_oca',
    ],
    'data': [
        'security/pos_forum_ventas_groups.xml',
        'security/ir.model.access.csv',
        'security/pos_forum_ventas_rules.xml',
        'views/pos_payment_views.xml',
        'report/pos_movimiento_caja_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
