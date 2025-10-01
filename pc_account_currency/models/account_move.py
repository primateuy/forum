from odoo import api, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.onchange('date', 'currency_id', 'journal_id', 'partner_id', 'invoice_line_ids')
    def _change_payable_receivable_account(self):
        for rec in self:
            account_id = rec.journal_id.account_currency_ids.filtered(lambda l: l.currency_id == rec.currency_id).account_id
            currency_account_receivable = rec.partner_id.property_account_receivable_id.currency_id.id if rec.partner_id.property_account_receivable_id.currency_id else rec.env.company.currency_id.id
            if rec.move_type in ['out_refund','out_invoice'] and rec.currency_id and rec.currency_id.id == currency_account_receivable:
                account_id = rec.partner_id.property_account_receivable_id
            currency_account_payable = rec.partner_id.property_account_payable_id.currency_id.id if rec.partner_id.property_account_payable_id.currency_id else rec.env.company.currency_id.id
            if rec.move_type in ['in_refund','in_invoice'] and rec.currency_id and rec.currency_id.id == currency_account_payable:
                account_id = rec.partner_id.property_account_payable_id

            if account_id and rec.journal_id.type != 'general':
                for line in rec.line_ids.filtered(lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable')):
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



