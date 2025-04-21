from odoo import models, fields, api, _
from datetime import datetime


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    intercompany_transfer_id = fields.Many2one("setu.intercompany.transfer","Intercompany Transfer", copy=False, index=True)

    # def action_view_invoice(self):
    #     res = super(PurchaseOrder, self).action_view_invoice()
    #     res['context'].update({'default_intercompany_transfer_id': self.intercompany_transfer_id.id})
    #     return res

    def _prepare_invoice(self):
        vals = super(PurchaseOrder, self)._prepare_invoice()
        if self.intercompany_transfer_id:
            date = self.date_order.date() or datetime.now().date()
            if date:
                vals.update({'invoice_date': date})
        return vals
