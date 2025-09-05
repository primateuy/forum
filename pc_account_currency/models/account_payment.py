from odoo import models, fields, api
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    _inherit = "account.payment"

    def _get_fist_journal(self):
        AccountAccount = self.env['account.journal']
        journal_ids = AccountAccount.search([('type', '=', 'sale')], limit=1)
        return journal_ids

    account_journal_id = fields.Many2one('account.journal', string='Journal Payment Account', default=lambda self: self._get_fist_journal())
    journal_ids_domain = fields.Binary(string="tag domain", help="Dynamic domain used for the account", compute="_compute_journal_ids_domain")

    @api.onchange('partner_type')
    def _get_change_journal(self):
        for rec in self:
            AccountAccount = self.env['account.journal']
            journal_ids = False
            if rec.partner_type == 'customer':
                journal_ids = AccountAccount.search([('type', '=', 'sale')], limit=1)
            elif rec.partner_type == 'supplier':
                journal_ids = AccountAccount.search([('type', '=', 'purchase')], limit=1)
            rec.account_journal_id = journal_ids

    @api.depends('partner_type')
    def _compute_journal_ids_domain(self):
        for rep_line in self:
            args = []
            AccountAccount = self.env['account.journal']
            journal_ids = None
            if rep_line.partner_type == 'customer':
                journal_ids = AccountAccount.search([('type', '=', 'sale')])
            elif rep_line.partner_type == 'supplier':
                journal_ids = AccountAccount.search([('type', '=', 'purchase')])
            if journal_ids:
                args = [('id', 'in', journal_ids.ids)]
            rep_line.journal_ids_domain = args

    def action_post(self):
        if 'dont_redirect_to_payments' not in self._context:
            self.change_account_payment()
        res = super().action_post()
        return res

    def change_account_payment(self):
        if self.payment_id.account_journal_id:
            account_id = self.payment_id.account_journal_id.account_currency_ids.filtered(lambda l: l.currency_id == self.currency_id).account_id
            currency_account_receivable = self.partner_id.property_account_receivable_id.currency_id.id if self.partner_id.property_account_receivable_id.currency_id else self.env.company.currency_id.id
            if self.payment_id.account_journal_id.type == 'sale' and self.currency_id.id == currency_account_receivable:
                account_id = self.partner_id.property_account_receivable_id

            currency_account_payable = self.partner_id.property_account_payable_id.currency_id.id if self.partner_id.property_account_payable_id.currency_id else self.env.company.currency_id.id
            if self.payment_id.account_journal_id.type == 'purchase' and self.currency_id.id == currency_account_payable:
                account_id = self.partner_id.property_account_payable_id

            if account_id and self.move_id.journal_id.type != 'general':
                for line in self.move_id.line_ids.filtered(lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable')):
                    line.account_id = account_id
        else:
            raise UserError("Debe configurar el Diario de Pago a Cuenta.")
