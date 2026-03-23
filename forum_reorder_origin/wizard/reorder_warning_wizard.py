# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class ForumReorderWarningWizard(models.TransientModel):
    _name = 'forum.reorder.warning.wizard'
    _description = 'Alerta de Stock Insuficiente en Origen'

    message = fields.Text(
        string='Mensaje',
        readonly=True,
    )
    orderpoint_ids = fields.Many2many(
        'stock.warehouse.orderpoint',
        string='Reglas de Reabastecimiento',
    )
    has_unfulfillable = fields.Boolean(default=True)

    def action_force_replenish(self):
        """Fuerza el reabastecimiento ignorando la validación de origen."""
        if self.orderpoint_ids:
            return super(
                type(self.orderpoint_ids), self.orderpoint_ids
            ).action_replenish()
        return {'type': 'ir.actions.act_window_close'}

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}
