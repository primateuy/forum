{
    "name": "FORUM - Cola de registro de facturas",
    "version": "17.0.1.0.0",
    "category": "Accounting",
    "author": "PrimateUY",
    "license": "LGPL-3",
    "summary": "Registrar facturas en lote en segundo plano, de a tandas",
    "description": """
Registrar muchas facturas juntas desde la lista revienta con un
``RecursionError`` del core de Odoo 17: la recursion que dispara el calculo de
``discount_allocation_dirty`` crece con la cantidad de lineas de la tanda y se
pasa del limite de Python.

Este modulo no postea en el momento: deja las facturas **en cola** y un cron las
va registrando de a tandas acotadas por cantidad de lineas, commiteando cada
tanda. El usuario no espera, y lo que salio queda guardado aunque una tanda
posterior falle.

Confirmar una factura sola desde su formulario sigue funcionando exactamente
igual que siempre, y la saca de la cola automaticamente.
    """,
    "depends": ["account"],
    "data": [
        "data/ir_config_parameter.xml",
        "data/ir_cron.xml",
        "views/account_move_views.xml",
    ],
    "installable": True,
    "application": False,
}
