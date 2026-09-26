# -*- coding: utf-8 -*-
{
    'name': 'FORUM — Perfil Sucursal × Costo de Gestión',
    'version': '17.0.1.0.0',
    'author': 'PRIMATE',
    'website': 'https://primate.uy',
    'category': 'Hidden/Tools',
    'license': 'LGPL-3',
    'summary': """Pone el costo de gestión bajo el mismo grupo que el resto de los
        costos, cuando los dos módulos están instalados.""",
    'description': """
        Módulo puente, con auto_install.

        primate_management_cost agrega el costo de gestión al producto y dos columnas al
        reporte de existencias. Si el perfil de sucursal ve ese reporte, ve el costo de
        gestión — y el reporte tiene vista pivot, donde las medidas se eligen en runtime
        desde fields_get, así que ocultarlas por presentación no alcanza.

        Esto va en un puente y no dentro de forum_branch_security para no obligarlo a
        depender de un módulo que todavía no está desplegado: primate_management_cost
        vive en bianalytics, en una rama sin mergear. Con auto_install el puente se
        instala solo el día que los dos estén presentes, y mientras tanto
        forum_branch_security funciona igual.
    """,
    'depends': [
        'forum_branch_security',
        'primate_management_cost',
    ],
    'auto_install': True,
    'installable': True,
}
