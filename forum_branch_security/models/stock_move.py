# -*- coding: utf-8 -*-
"""Envío a otra sucursal: los movimientos encadenados se confirman y se validan como sistema.

El local manda mercadería con «Intercambio - Envíos» a la Salida de la sucursal
destino, y las reglas push de la ruta de esa sucursal arman el resto:

    Salida X   → Tránsito X        automática, sin paso agregado
    Tránsito X → X/Existencias     manual, en un tipo de operación de X

El core crea el movimiento encadenado como superusuario (`_run_push` hace
`move.sudo().copy()`), pero todo lo de alrededor —preparar sus valores, confirmarlo,
armarle la transferencia en el tipo de operación de X— lo corre con el usuario que
apretó «Marcar por realizar». El perfil de sucursal no le deja leer ubicaciones,
movimientos ni tipos de operación de otro almacén, así que cortaba con AccessError
sobre X/Existencias (support, 20-10-2026, stock.location 110).

Es el mismo criterio que ya aplica el core al abastecimiento: `_run_pull` crea y
confirma los movimientos como superusuario porque el usuario que dispara la
necesidad puede no tener permisos sobre ellos. Lo que se eleva es sólo lo que las
reglas generan solas; el usuario sigue sin VER la otra sucursal.
"""
from odoo import models


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _push_apply(self):
        """Para el perfil de sucursal, las reglas push corren como sistema.

        Los movimientos nuevos vuelven con `sudo`, y así el `_action_confirm` que el
        core les aplica después —y la transferencia que les crea en la otra sucursal—
        también. `create_uid` sigue siendo el usuario: `sudo()` no cambia el uid.
        """
        if self.env.su or not self.env.user.has_group('forum_branch_security.group_branch_user'):
            return super()._push_apply()
        return super(StockMove, self.sudo())._push_apply()

    def _action_done(self, cancel_backorder=False):
        """Para el perfil de sucursal, validar corre como sistema.

        Al validar, el core recorre los movimientos siguientes de la cadena —la recepción
        en la otra sucursal—: los lee para ver si corta el vínculo
        (`_check_unlink_move_dest`) y para agruparlos por compañía antes de reservarlos.
        La reserva ya la hace como superusuario, pero la lectura previa no, y el perfil no
        ve movimientos de otra sucursal: «Usuario - Suc. Centro no tiene acceso 'leer' a
        Movimiento de stock» al validar un Intercambio - Envío a Maldonado (support,
        02-11-2026).

        El usuario ya pasó el control de acceso al apretar Validar sobre SU operación;
        `sudo()` no cambia el uid, así que la validación queda registrada a su nombre.
        """
        if self.env.su or not self.env.user.has_group('forum_branch_security.group_branch_user'):
            return super()._action_done(cancel_backorder=cancel_backorder)
        hechos = super(StockMove, self.sudo())._action_done(cancel_backorder=cancel_backorder)
        return hechos.with_env(self.env)
