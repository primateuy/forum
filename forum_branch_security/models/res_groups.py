# -*- coding: utf-8 -*-
"""La vista consolidada del perfil.

Para entender qué ve un perfil hoy hay que mirar en cinco lugares distintos: la pestaña
de menús del grupo, los Security Fields en ir.model, el menú de
generic.security.model.restriction, cada ir.actions.report uno por uno, y los permisos de
acceso en Técnico. Eso no es administrable.

`res.groups` ya trae de generic_security_restriction los inversos de menús
(`menu_access_only`), de restricciones de registro (`model_restriction_ids`) y de reportes
ocultos (`hidden_report_ids`). Faltan los de restricciones de campo y los de ACL, que se
agregan acá — sin tocar el módulo de pago.
"""
from odoo import models, fields


class ResGroups(models.Model):
    _inherit = 'res.groups'

    # Inverso de generic.security.restriction.field.group_ids.
    #
    # Ojo con los nombres de columna: en el módulo original el m2m se declara como
    #   Many2many('res.groups', 'fields_security_restriction_group_relation',
    #             'group_id', 'field_security_id')
    # o sea que column1 ('group_id') guarda el id de la RESTRICCION y column2
    # ('field_security_id') el del GRUPO. Los nombres están cruzados respecto de lo que
    # sugieren. El inverso tiene que respetar ese cruce, no los nombres.
    branch_field_restriction_ids = fields.Many2many(
        comodel_name='generic.security.restriction.field',
        relation='fields_security_restriction_group_relation',
        column1='field_security_id',
        column2='group_id',
        string='Restricciones de campo',
        help='Campos ocultos, de solo lectura o con el botón estadístico escondido '
             'para este grupo.',
    )

    branch_access_ids = fields.One2many(
        comodel_name='ir.model.access',
        inverse_name='group_id',
        string='Permisos de acceso',
        help='Las ACL del grupo: qué modelos puede leer, escribir, crear y borrar.',
    )
