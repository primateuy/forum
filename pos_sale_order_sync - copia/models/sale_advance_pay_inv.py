from odoo import models, fields, api


class SaleAdvancePaymentInv(models.TransientModel):
    _inherit = "sale.advance.payment.inv"

    numero_lineas = fields.Integer('Cantidad Líneas', compute='compute_numero_lineas')

    @api.depends('sale_order_ids')
    def compute_numero_lineas(self):
        for rec in self:
            rec.numero_lineas = sum(rec.sale_order_ids.mapped('numero_lineas'))
