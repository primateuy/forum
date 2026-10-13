# -*- coding: utf-8 -*-
"""Punto de entrada de la cadena de tandas de reposición (ver models/reposicion_proceso.py)."""
import logging

from odoo import SUPERUSER_ID, api, http
from odoo.http import request

from ..models.reposicion_proceso import RUTA

_logger = logging.getLogger(__name__)


class ForumReposicionController(http.Controller):

    @http.route(RUTA, type='json', auth='none', methods=['POST'], csrf=False, save_session=False)
    def tanda(self, token=None, **_kw):
        """Corre una tanda. No hay usuario: la autoriza el token del parámetro del sistema."""
        if not request.db:
            return {'estado': 'sin base'}
        env = api.Environment(request.env.cr, SUPERUSER_ID, {})
        try:
            return env['forum.reposicion.proceso']._correr_tanda(token)
        except Exception:
            _logger.exception("[reposición] falló la tanda")
            raise
