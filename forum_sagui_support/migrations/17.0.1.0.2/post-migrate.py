# -*- coding: utf-8 -*-
# Revive el cron en las bases donde ya se instaló con el `numbercall` por defecto.
#
# El registro del cron es `noupdate`, así que arreglar el XML no alcanza: en una base existente
# ningún `<record>` posterior lo toca. Es la misma trampa del bot archivado de 17.0.1.0.1.
#
# Lo que pasaba: con `numbercall` en 1, el cron corre UNA vez, Odoo lo decrementa a 0 y lo
# desactiva. Nada falla, nada se loguea: simplemente el piso de latencia deja de existir a los
# sesenta segundos de instalar, y las respuestas del responsable sólo llegan si hay long-poll.
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref("forum_sagui_support.cron_sagui_traer_respuestas", raise_if_not_found=False)
    if not cron:
        return
    cron.sudo().write({"numbercall": -1, "doall": False, "active": True})
    _logger.info("Sagui soporte: cron de la cola reactivado (numbercall=-1)")
