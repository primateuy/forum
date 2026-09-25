# -*- coding: utf-8 -*-
{
    'name': 'FORUM — Perfil Usuario Sucursal',
    'version': '17.0.1.0.0',
    'author': 'PRIMATE',
    'website': 'https://primate.uy',
    'category': 'Hidden/Tools',
    'license': 'LGPL-3',
    'summary': """Perfil de permisos del usuario de local: qué ve, qué puede tocar y qué
        no, sin crear ni archivar una sola regla de registro.""",
    'description': """
        El perfil de permisos que se apoya en el ancla de sucursal de retail_branch.

        Todo el recorte se hace con generic_security_restriction, que AND-ea un dominio
        extra dentro de ir.rule._compute_domain. No se crea ninguna ir.rule nueva ni se
        archiva ninguna existente, porque las reglas multicompañía de core son globales y
        las globales se combinan con AND: agregar una regla nunca amplía lo que otra
        permite ver, y archivarlas para ensanchar deja la base sin su recorte de
        compañía.

        Lo que sí ensancha es company_ids, que sincroniza retail_branch, y la jerarquía
        de compañías, que ya está declarada.

        El costo se oculta con el atributo groups= nativo sobre el campo, no con la capa
        de presentación: Odoo lo aplica en fields_get y en el read del ORM, así que el
        campo ni se lee. La capa de generic_security_restriction queda para lo que es
        efectivamente de presentación.
    """,
    'depends': [
        'retail_branch',
        'generic_security_restriction',
        'stock',
        'point_of_sale',
        'tchistorico',
    ],
    'data': [
        'security/branch_groups.xml',
        'security/ir.model.access.csv',
        'views/stock_query_views.xml',
        'views/res_groups_views.xml',
        'data/record_restrictions.xml',
        'data/field_restrictions.xml',
        'data/menu_whitelist.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
