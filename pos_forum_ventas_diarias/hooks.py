# -*- coding: utf-8 -*-
"""
Alta del menú en la lista blanca de los perfiles de sucursal.

forum_branch_security restringe lo que ven los perfiles de local con una lista
blanca de menús (campo menu_access_only): lo que no está listado no se ve,
incluidos los menús que agregue un módulo posterior. Sin este paso, un usuario
de sucursal con el grupo de consulta tendría el permiso pero no vería la
entrada de menú.

Se hace por hook y no por XML porque el archivo de la lista blanca está marcado
como noupdate: el XML solo siembra la línea base y de ahí en más manda lo que
se configure desde la interfaz, así que una actualización no lo tocaría.
"""

import logging

_logger = logging.getLogger(__name__)

# Perfiles de forum_branch_security a los que se les habilita el menú.
PERFILES_SUCURSAL = (
    'forum_branch_security.group_branch_user',
    'forum_branch_security.group_branch_supervisor',
)

MENU_XMLID = 'pos_forum_ventas_diarias.menu_pos_payment_report_forum'


def post_init_hook(env):
    """
    Agrega el menú del módulo a la lista blanca de los perfiles de sucursal.

    No falla si forum_branch_security no está instalado: en ese caso no hay
    lista blanca que actualizar y el menú se rige solo por el grupo.

    Args:
        env: entorno de Odoo. Desde la versión 17 el hook recibe el env ya
            armado, no la dupla (cr, registry) de versiones anteriores.
    """
    menu = env.ref(MENU_XMLID, raise_if_not_found=False)
    if not menu:
        _logger.warning('No se encontró el menú %s; no se actualiza la lista blanca.', MENU_XMLID)
        return

    # El campo lo aporta generic_security_restriction. Si no está, no hay
    # lista blanca que mantener.
    if 'menu_access_only' not in env['res.groups']._fields:
        _logger.info(
            'El campo menu_access_only no existe en esta base: '
            'no hay lista blanca de menús que actualizar.'
        )
        return

    actualizados = []
    for xmlid in PERFILES_SUCURSAL:
        grupo = env.ref(xmlid, raise_if_not_found=False)
        if not grupo:
            continue
        # Solo se toca la lista blanca de los perfiles que ya la tengan
        # poblada. Un perfil con la lista vacía no está restringiendo nada, y
        # agregarle una única entrada le recortaría todos los demás menús.
        if not grupo.menu_access_only:
            _logger.info(
                'El perfil %s no tiene lista blanca cargada: se omite para no '
                'restringirle el resto de los menús.', xmlid,
            )
            continue
        if menu not in grupo.menu_access_only:
            grupo.write({'menu_access_only': [(4, menu.id)]})
            actualizados.append(xmlid)

    if actualizados:
        _logger.info(
            'Menú «Ventas por forma de pago» habilitado en los perfiles: %s',
            ', '.join(actualizados),
        )
