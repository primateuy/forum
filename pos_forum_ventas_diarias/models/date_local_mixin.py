# -*- coding: utf-8 -*-
"""
Corte por día calendario local para los filtros de fecha.

Los campos Datetime se guardan en UTC. Un filtro armado en la vista con
``datetime.datetime.combine(context_today(), datetime.time(0,0,0))`` produce
una medianoche *naive* con la fecha del usuario, que el servidor compara
directo contra la columna UTC: en Uruguay (UTC-3) «Hoy» arrancaba a las 21:00
del día anterior y se cortaba a las 20:59, así que un local que cierra a las
22:00 veía su propio cierre en el día equivocado.

El evaluador de dominios del navegador no puede arreglarlo: conoce la fecha
local (``context_today()``) pero no el desfase de la zona. La conversión tiene
que pasar en el servidor, y de eso se encarga este mixin.

El campo date_local no se almacena: existe solo para que los filtros puedan
mandar una fecha pura (``'2026-10-06'``, sin hora ni zona, sin ambigüedad) y
que el método search la traduzca al rango UTC que le corresponde sobre el
campo Datetime real. Como el dominio resultante sigue apuntando al campo
original, el índice de ese campo se aprovecha igual.
"""

import logging
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.osv import expression

_logger = logging.getLogger(__name__)

# Último recurso cuando el usuario no tiene zona horaria configurada. El
# módulo es exclusivo de FORUM, así que caer a Montevideo deja los cortes
# bien; caer a UTC los dejaría corridos tres horas sin que nadie se entere.
TZ_POR_DEFECTO = 'America/Montevideo'


class PosForumDateLocalMixin(models.AbstractModel):
    """
    Expone el día calendario local del campo Datetime que indique el modelo.

    El modelo que lo hereda declara en _date_local_source el nombre de su
    campo Datetime de origen (payment_date, date, etc.).
    """

    _name = 'pos.forum.date.local.mixin'
    _description = 'Día calendario local de un campo de fecha y hora'

    # Lo define cada modelo que hereda el mixin.
    _date_local_source = None

    date_local = fields.Date(
        string='Día',
        compute='_compute_date_local',
        search='_search_date_local',
        help='Día calendario en la zona horaria del usuario. No se almacena: '
             'sirve para filtrar, no para agrupar.',
    )

    # ------------------------------------------------------------------
    # Zona horaria y conversión
    # ------------------------------------------------------------------

    def _date_local_tz(self):
        """Devuelve la zona horaria del usuario, con Montevideo de respaldo."""
        nombre = self.env.context.get('tz') or self.env.user.tz
        if not nombre:
            _logger.warning(
                'El usuario %s no tiene zona horaria configurada; los filtros '
                'de fecha de %s usan %s.',
                self.env.user.login, self._name, TZ_POR_DEFECTO,
            )
            nombre = TZ_POR_DEFECTO
        try:
            return pytz.timezone(nombre)
        except pytz.UnknownTimeZoneError:
            _logger.warning(
                'Zona horaria desconocida %r; los filtros de fecha de %s usan %s.',
                nombre, self._name, TZ_POR_DEFECTO,
            )
            return pytz.timezone(TZ_POR_DEFECTO)

    def _date_local_inicio_utc(self, fecha):
        """
        Traduce la medianoche local de una fecha al instante UTC equivalente.

        Devuelve un datetime naive, que es lo que el ORM espera en un dominio
        sobre un campo Datetime.
        """
        local = self._date_local_tz().localize(
            datetime.combine(fecha, time.min), is_dst=False,
        )
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    # ------------------------------------------------------------------
    # Compute y search
    # ------------------------------------------------------------------

    @api.depends(lambda self: [self._date_local_source] if self._date_local_source else [])
    def _compute_date_local(self):
        """Pasa el valor UTC del campo de origen al día calendario local."""
        tz = self._date_local_tz()
        campo = self._date_local_source
        for registro in self:
            valor = campo and registro[campo]
            registro.date_local = (
                pytz.utc.localize(valor).astimezone(tz).date() if valor else False
            )

    def _search_date_local(self, operator, value):
        """
        Traduce una comparación por día local a un rango UTC sobre el origen.

        Cada día local es un intervalo semiabierto [inicio, inicio del día
        siguiente) en UTC, así que los operadores estrictos se corren al día
        que sigue en lugar de comparar contra la misma medianoche.
        """
        campo = self._date_local_source
        if not campo:
            raise NotImplementedError(
                'El modelo %s hereda el mixin de día local sin declarar '
                '_date_local_source.' % self._name
            )

        # Registros sin fecha: no hay nada que convertir.
        if value is False or value is None:
            if operator in ('=', 'in'):
                return [(campo, '=', False)]
            return [(campo, '!=', False)]

        if operator in ('in', 'not in'):
            valores = value if isinstance(value, (list, tuple)) else [value]
            # Cada día es un rango de dos condiciones, así que la unión se
            # arma con expression.OR y no concatenando '|': de lo contrario
            # el operador quedaría atado solo a la primera de las dos.
            opuesto = '!=' if operator == 'not in' else '='
            combinar = expression.AND if operator == 'not in' else expression.OR
            return combinar([self._search_date_local(opuesto, f) for f in valores])

        fecha = fields.Date.to_date(value)
        inicio = self._date_local_inicio_utc(fecha)
        siguiente = self._date_local_inicio_utc(fecha + timedelta(days=1))

        if operator == '=':
            return [(campo, '>=', inicio), (campo, '<', siguiente)]
        if operator == '!=':
            return ['|', (campo, '<', inicio), (campo, '>=', siguiente)]
        if operator == '>=':
            return [(campo, '>=', inicio)]
        if operator == '>':
            return [(campo, '>=', siguiente)]
        if operator == '<':
            return [(campo, '<', inicio)]
        if operator == '<=':
            return [(campo, '<', siguiente)]

        raise NotImplementedError(
            'Operador %r no soportado sobre date_local.' % operator
        )
