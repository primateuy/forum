# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PurchaseRequisition(models.Model):
    _inherit = "purchase.requisition"

    currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency_id",
        store=True,
        readonly=True,
    )
    total_qty = fields.Float(string="Cantidad total", compute="_compute_totals", store=True, readonly=True)
    total_amount = fields.Monetary(string="Monto total", currency_field="currency_id", compute="_compute_totals", store=True, readonly=True)

    @api.depends("company_id")
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = rec.company_id.currency_id

    @api.depends("line_ids.product_qty", "line_ids.price_unit")
    def _compute_totals(self):
        for rec in self:
            qty = 0.0
            amt = 0.0
            for line in rec.line_ids:
                qty += line.product_qty or 0.0
                amt += (line.product_qty or 0.0) * (line.price_unit or 0.0)
            rec.total_qty = qty
            rec.total_amount = amt

    def action_open_variant_matrix(self):
        self.ensure_one()
        # Wizard model provided by product_matrix / purchase_product_matrix (OCA)
        wizard_model = "product.matrix.wizard"
        if not self.env["ir.model"].search([("model", "=", wizard_model)], limit=1):
            raise UserError(_("No se encontró el wizard de matriz (%s). Verifique que 'purchase_product_matrix' esté instalado.") % wizard_model)

        return {
            "type": "ir.actions.act_window",
            "name": _("Agregar variantes"),
            "res_model": wizard_model,
            "view_mode": "form",
            "target": "new",
            "context": {
                "active_model": "purchase.requisition",
                "active_id": self.id,
            },
        }
