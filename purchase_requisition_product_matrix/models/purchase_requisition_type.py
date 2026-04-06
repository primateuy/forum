# -*- coding: utf-8 -*-

from odoo import api, fields, models


class PurchaseRequisitionType(models.Model):
    _inherit = 'purchase.requisition.type'

    use_remaining_qty = fields.Boolean(
        string='Traer cantidades remanentes',
        default=False,
        help="Al crear una orden de compra desde este tipo de acuerdo, sugiere "
             "la diferencia entre la cantidad del contrato y lo ya pedido en "
             "órdenes confirmadas.",
    )

    @api.onchange('quantity_copy')
    def _onchange_quantity_copy(self):
        if self.quantity_copy != 'copy':
            self.use_remaining_qty = False
