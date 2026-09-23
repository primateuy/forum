# -*- coding: utf-8 -*-
# Arregla las bases donde el bot se creó con `active=False` en el XML y quedó también el PARTNER
# archivado. El dato no puede arreglarlo: su xmlid está marcado `noupdate`, así que ningún
# `<record>` posterior lo toca. Por eso va una migración.
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.forum_sagui_support.models.res_users import archivar_bot
    archivar_bot(env)
    _logger.info("Sagui soporte: contacto del bot reactivado, usuario archivado")
