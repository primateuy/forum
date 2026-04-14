from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = "sale.order"

    numero_lineas = fields.Integer('Cantidad Líneas', compute='compute_numero_lineas', store=True)

    @api.depends('order_line')
    def compute_numero_lineas(self):
        for rec in self:
            rec.numero_lineas = len(rec.order_line)

    def auto_validate_pickings(self):
        for order in self:
            pickings = order.picking_ids.filtered(lambda p: p.state == "assigned")

            for picking in pickings:
                # picking.action_confirm()

                # if picking.state in ("confirmed", "waiting"):
                #     picking.action_assign()

                # Set done quantities automatically
                for move in picking.move_ids_without_package:
                    move.quantity = move.product_uom_qty

                # Validate picking
                picking.button_validate()
