from odoo import api, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.onchange('date', 'currency_id', 'journal_id', 'partner_id', 'invoice_line_ids')
    def _change_payable_receivable_account(self):
        account_id = self.journal_id.account_currency_ids.filtered(lambda l: l.currency_id == self.currency_id).account_id
        currency_account_receivable = self.partner_id.property_account_receivable_id.currency_id.id if self.partner_id.property_account_receivable_id.currency_id else self.env.company.currency_id.id
        if self.move_type in ['out_refund', 'out_invoice'] and self.currency_id.id == currency_account_receivable:
            account_id = self.partner_id.property_account_receivable_id
        currency_account_payable = self.partner_id.property_account_payable_id.currency_id.id if self.partner_id.property_account_payable_id.currency_id else self.env.company.currency_id.id
        if self.move_type in ['in_refund', 'in_invoice'] and self.currency_id.id == currency_account_payable:
            account_id = self.partner_id.property_account_payable_id

        if account_id and self.journal_id.type != 'general':
            for line in self.line_ids.filtered(lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable')):
                line.account_id = account_id

    def action_post(self):
        """ Before validate invoice change account for line with account_type in ('asset_receivable', 'liability_payable')"""
        self._change_payable_receivable_account()
        res = super().action_post()
        return res
    
    def create(self, vals):
        """ Before create invoice change account for line with account_type in ('asset_receivable', 'liability_payable')"""
        res = super().create(vals)
        res._change_payable_receivable_account()
        return res



