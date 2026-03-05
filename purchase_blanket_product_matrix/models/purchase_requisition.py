# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class PurchaseRequisition(models.Model):
    _inherit = "purchase.requisition"

    total_qty = fields.Float(string="Cantidad total", compute="_compute_totals", store=True)
    total_amount = fields.Monetary(string="Monto total", currency_field="currency_id",
                                   compute="_compute_totals", store=True)
    currency_id = fields.Many2one("res.currency", string="Moneda",
                                  compute="_compute_currency_id", store=True, readonly=True)

    @api.depends("company_id")
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = rec.company_id.currency_id

    @api.depends("line_ids.product_qty", "line_ids.price_unit")
    def _compute_totals(self):
        for rec in self:
            qty = 0.0
            amount = 0.0
            for line in rec.line_ids:
                qty += line.product_qty or 0.0
                amount += (line.product_qty or 0.0) * (line.price_unit or 0.0)
            rec.total_qty = qty
            rec.total_amount = amount

    def action_open_variant_matrix(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Seleccione las variantes del producto"),
            "res_model": "purchase.requisition.matrix.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "active_model": "purchase.requisition",
                "active_id": self.id,
            },
        }
