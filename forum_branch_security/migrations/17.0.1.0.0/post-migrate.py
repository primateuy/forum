# -*- coding: utf-8 -*-
"""Migración del perfil de sucursal.

Para un módulo NUEVO este script no corre: Odoo solo ejecuta migrations/<version>/ cuando
la versión instalada cambia, y en la primera instalación el punto de entrada es el
post_init_hook. Está acá para el caso de que el módulo se actualice sobre un estado
anterior, y llama exactamente a la misma función, que es idempotente.
"""
import logging

from odoo import api, SUPERUSER_ID

from odoo.addons.forum_branch_security.hooks import post_init_hook

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    _logger.info('Perfil sucursal: re-ejecutando la siembra desde la migración.')
    post_init_hook(env)
