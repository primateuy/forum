from odoo import models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def button_confirm(self):
        res = super().button_confirm()

        # Solo para órdenes intercompany auto-generadas
        intercompany_pos = self.filtered(lambda po: po.auto_generated)

        for po in intercompany_pos:
            po._auto_validate_intercompany_pickings()

        return res

    def _auto_validate_intercompany_pickings(self):
        for po in self:
            pickings = po.picking_ids.filtered(lambda p: p.state == 'assigned')

            for picking in pickings:
                # # Confirmar picking
                # if picking.state == "draft":
                #     picking.action_confirm()

                # # Reservar stock
                # if picking.state in ("confirmed", "waiting"):
                #     picking.action_assign()

                # Completar cantidades
                for move in picking.move_ids_without_package:
                    move.quantity = move.product_uom_qty

                # Validar transferencia
                picking.button_validate()
