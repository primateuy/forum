# -*- coding: utf-8 -*-
"""Sincronización con `allowed_pos`, de pos_restrict.

`pos_restrict` no es un módulo redundante que se pueda desinstalar: **sus cuatro reglas
gobiernan el acceso al PDV de todos los usuarios**, no solo los de sucursal.

    pos.config  [('id','in', user.allowed_pos.ids)]           grupo: PDV / Usuario
    pos.config  []                                            grupo: PDV / Administrador
    pos.order   [('config_id','in', user.allowed_pos.ids)]    grupo: PDV / Usuario
    pos.order   []                                            grupo: PDV / Administrador

El perfil de sucursal implica `point_of_sale.group_pos_user`, así que esas reglas se le
aplican. Y como son reglas de registro, se combinan con AND con nuestra restricción: si
`allowed_pos` y `branch_pos_config_ids` no coinciden, la intersección queda vacía y el
usuario **no ve ningún PDV**.

Por eso el ancla manda sobre `allowed_pos`: al asignar la sucursal se agregan sus PDV.
Solo agrega, igual que con las compañías — un usuario puede tener acceso a un PDV por
otro motivo que este módulo no conoce.

La sincronización es condicional: si pos_restrict no está instalado no hace nada, y el
módulo instala igual.
"""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _sync_branch_companies(self):
        """Extiende la sincronización del ancla para cubrir también el PDV."""
        result = super()._sync_branch_companies()
        self._sync_branch_pos_access()
        return result

    def _sync_branch_pos_access(self):
        if 'allowed_pos' not in self._fields:
            return
        for user in self:
            configs = user.branch_warehouse_ids.branch_pos_config_ids
            if not configs:
                continue
            faltan = configs - user.allowed_pos
            if not faltan:
                continue
            _logger.info(
                'Sucursal: se agregan los PDV %s a allowed_pos de %s.',
                ', '.join(faltan.mapped('name')), user.login)
            user.sudo().write({'allowed_pos': [(4, c.id) for c in faltan]})
