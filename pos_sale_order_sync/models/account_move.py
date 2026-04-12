from odoo import models, api
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    @api.model_create_multi
    def create(self, vals_list):
        new_ids = super(AccountMove, self).create(vals_list)
        if self.env.context.get("autoinvoice_bypass_line_limit"):
            return new_ids
        for new_id in new_ids.filtered(lambda l: l.move_type == 'out_invoice' and l.journal_id.punto_emision_id):
            if len(new_id.invoice_line_ids) > new_id.journal_id.punto_emision_id.max_numero_lineas:
                raise UserError('No es posible crear la factura ya que su cantidad máxima de líneas es %s' % new_id.journal_id.punto_emision_id.max_numero_lineas)
        return new_ids
