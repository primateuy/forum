# -*- coding: utf-8 -*-
"""El tramo puente del intercambio entre sucursales lo ejecuta el código, no el usuario.

El intercambio entre sucursales de FORUM son tres tramos, de los cuales el operador
sólo conoce el primero:

1. `Sucursal origen → POLO/Salida <Destino>`, el *Intercambio - Envio* que valida él.
   El destino se lo pone el contacto de la sucursal de destino con su *Ubicación del
   cliente* (ver `_branch_operation_location_ids`, en `res_users`).
2. `POLO/Salida <Destino> → Tránsito <Destino>`, invisible: una regla push
   `transparent` que sólo cambia el destino del movimiento, sin agregar una operación.
3. `Tránsito <Destino> → Existencias <Destino>`, la recepción que valida la **otra**
   sucursal: una regla push `manual`, que crea el picking en el almacén de destino.

Los tramos 2 y 3 los aplica `stock.move._push_apply()` dentro del `_action_confirm` del
envío, o sea **en la transacción del usuario que envía**. El tramo 2 pasa sin permisos
nuevos, porque la ubicación de tránsito es `usage='transit'` y el dominio del perfil ya
deja ver las contrapartes del circuito. El que rompe es el tramo 3:

    Access Denied by record rules for operation: read
    on record ids: [110], uid: 230, model: stock.location   ← 042/CARMELO/Existencias

La ubicación de existencias de la sucursal de destino es `internal` y de otro almacén:
es exactamente lo que el perfil oculta, y tiene que seguir ocultándolo. El usuario no la
elige ni la ve; sale de la regla push que el core resuelve por él.

El core ya eleva **parte** del push —`move.sudo().copy(...)` en `stock_rule._run_push`, y
`(new_push_moves).sudo()._action_confirm()` en `stock_move._action_confirm`— pero no la
resolución de la regla ni la preparación de sus valores, que corren como el usuario. Acá
se eleva la aplicación entera, que es la unidad que tiene sentido: o el circuito se aplica
completo o no se aplica.

**Esto no le ensancha nada al usuario.** Sigue sin ver el picking de recepción, la
ubicación de destino ni el almacén de la otra sucursal: lo elevado es la ejecución del
tramo, no lo que el perfil le muestra. Es la misma figura que el core usa cuando el
destino es de otra compañía (`stock_move._push_apply`, rama del `else`).
"""
from odoo import models


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _push_apply(self):
        """Aplica las reglas push elevado cuando el que confirma es de sucursal.

        Se acota al perfil a propósito: para cualquier otro usuario el
        comportamiento del core queda intacto, incluidos los `AccessError` que
        hoy avisan de una configuración de rutas mal armada.
        """
        if self.env.su or not self.env.user.has_group(
                'forum_branch_security.group_branch_user'):
            return super()._push_apply()
        return super(StockMove, self.sudo())._push_apply()

    def _action_done(self, cancel_backorder=False):
        """Validar el envío tampoco puede tropezar con el tramo que sigue.

        Confirmar crea el movimiento de la otra sucursal; validar lo **lee**,
        para propagarle la reserva (`stock_move._action_done`):

            moves_todo._check_unlink_move_dest()
            for move_dest in moves_todo.move_dest_ids:      ← AccessError
                move_dests_per_company[move_dest.company_id.id] |= move_dest
            for company_id, move_dests in ...:
                move_dests.sudo().with_company(company_id)._action_assign()

        El core eleva la reserva del tramo siguiente, pero no la lectura previa
        que lo agrupa por compañía. Con el perfil puesto, ese movimiento está
        fuera de las ubicaciones del usuario y la lectura falla.

        Se eleva sólo cuando hace falta —cuando hay un tramo encadenado que el
        usuario no puede leer—, no en toda validación: una entrega de PdV o una
        recepción del propio local siguen corriendo con sus permisos.
        """
        if self._branch_eleva_la_cadena():
            return super(StockMove, self.sudo())._action_done(
                cancel_backorder=cancel_backorder)
        return super()._action_done(cancel_backorder=cancel_backorder)

    def _branch_eleva_la_cadena(self):
        """¿Hay un tramo encadenado que este usuario de sucursal no puede leer?"""
        if self.env.su or not self.env.user.has_group(
                'forum_branch_security.group_branch_user'):
            return False
        encadenados = self.sudo().move_dest_ids
        if not encadenados:
            return False
        legibles = self.env['stock.move'].search([('id', 'in', encadenados.ids)])
        return len(legibles) != len(encadenados)
