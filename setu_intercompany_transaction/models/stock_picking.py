from odoo import models, fields, api, _


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    ict_internal_transfer_id = fields.Many2one("setu.intercompany.transfer", "Inter Warehouse Transfer")
    sale_intercompany_transfer_id = fields.Many2one("setu.intercompany.transfer","Intercompany Transfer",
                                               related='sale_id.intercompany_transfer_id')

    purchase_intercompany_transfer_id = fields.Many2one("setu.intercompany.transfer","Intercompany Transfer",
                                                    related='purchase_id.intercompany_transfer_id')

    def button_validate(self):
        res = super(StockPicking, self).button_validate()
        ict = self.sale_intercompany_transfer_id or self.purchase_intercompany_transfer_id
        if ict and ict.auto_workflow_id and ict.auto_workflow_id.create_ict_invoices:
            ict.with_company(self.company_id).action_create_ict_invoices()
            if ict.auto_workflow_id.validate_ict_invoices:
                ict.with_company(self.company_id).action_validate_ict_invoices()
        return res
