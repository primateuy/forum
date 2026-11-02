# -*- coding: utf-8 -*-
"""Aviso de demora de una recepción que espera una operación de otro almacén.

La lista de transferencias muestra un reloj en las demoradas (`json_popover`), y el
core lo arma con el nombre de las operaciones que demoran la recepción. En
«Recepcion desde Deposito Central» esas son las salidas de POLO, que el perfil de
sucursal no puede leer: la lista entera caía con «no tiene acceso 'leer' a
Transferir» (support, Suc. Centro, 002/POLO-IN/00002, 02-11-2026).
"""
import json

from odoo import models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _compute_json_popover(self):
        """Para el perfil de sucursal, el aviso se arma como sistema.

        Se mantiene la fecha de demora y de las operaciones que demoran sólo quedan
        las que el usuario puede abrir: el resto, al hacerle clic, daría el mismo
        error. El usuario sigue sin ver POLO.
        """
        if self.env.su or not self.env.user.has_group('forum_branch_security.group_branch_user'):
            return super()._compute_json_popover()
        como_sistema = self.sudo()
        super(StockPicking, como_sistema)._compute_json_popover()
        for picking, calculado in zip(self, como_sistema):
            datos = calculado.json_popover and json.loads(calculado.json_popover)
            if datos:
                datos['late_elements'] = [
                    elemento for elemento in datos.get('late_elements', [])
                    if self._branch_puede_leer(elemento['model'], elemento['id'])
                ]
            picking.json_popover = json.dumps(datos) if datos else False

    def _branch_puede_leer(self, modelo, res_id):
        registro = self.env[modelo].browse(res_id)
        return (registro.check_access_rights('read', raise_exception=False)
                and bool(registro._filter_access_rules('read')))
