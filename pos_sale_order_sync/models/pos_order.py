from odoo import models, fields, api


class PosOrder(models.Model):
    _inherit = "pos.order"

    sale_order_id = fields.Many2one("sale.order", "Orden creada", readonly=True, copy=False)

    def create_sale_order_from_pos(self):
        self = self.sudo()

        for pos_order in self:
            if pos_order.sale_order_id:
                continue

            hay_productos = len(pos_order.lines.mapped('product_id').filtered(lambda p: not p.excluir_logica_franquicia)) > 0

            if not hay_productos:
                continue

            child_company_id = pos_order.company_id
            matrix_company_id = child_company_id.parent_id

            sale_order = self.env['sale.order'].create({
                "type_id": pos_order.config_id.sudo().tipo_pedido_venta_id.id,
                "partner_id": child_company_id.partner_id.id,
                "origin": pos_order.name,
                "company_id": matrix_company_id.id,
                "pricelist_id": pos_order.config_id.tipo_pedido_venta_id.pricelist_id.id,
            })

            for line in pos_order.lines:
                if not line.product_id.excluir_logica_franquicia:
                    self.env["sale.order.line"].create({
                        "order_id": sale_order.id,
                        "product_id": line.product_id.id,
                        "product_uom_qty": line.qty,
                        "price_unit": line.price_unit,
                        "discount": line.discount,
                        "name": line.product_id.display_name,
                    })

            sale_order.action_confirm()
            sale_order.auto_validate_pickings()

            pos_order.write({
                'sale_order_id': sale_order.id
            })

    def action_pos_order_paid(self):
        res = super().action_pos_order_paid()

        for rec in self:
            if rec.config_id and rec.config_id.crear_order_venta and rec.config_id.tipo_pedido_venta_id:
                rec.create_sale_order_from_pos()

        return res
