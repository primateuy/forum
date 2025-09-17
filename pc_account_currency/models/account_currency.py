from odoo import fields, models, api


class AccountCurrency(models.Model):
    _name = 'account.currency'
    _description = 'Account by Currency Line'

    journal_id = fields.Many2one('account.journal', string='Journal')
    currency_id = fields.Many2one('res.currency', string='Currency')
    account_id = fields.Many2one('account.account', string='Account')
    account_ids_domain = fields.Binary(string="tag domain", help="Dynamic domain used for the account", compute="_compute_account_ids_domain")

    @api.depends('journal_id.type', 'journal_id')
    def _compute_account_ids_domain(self):
        for rep_line in self:
            args = []
            if rep_line.journal_id:
                AccountAccount = self.env['account.account']
                account_ids = None
                # Busca los tipos de cuentas segun el tipo de diario
                # Cuentas por cobrar: asset_receivable - diario de Ventas
                # Cuentas por pagar: liability_payable - diario de Compras
                if rep_line.journal_id.type == 'sale':
                    account_ids = AccountAccount.search([('account_type', '=', 'asset_receivable')])
                elif rep_line.journal_id.type == 'purchase':
                    account_ids = AccountAccount.search([('account_type', '=', 'liability_payable')])
                if account_ids:
                    args = [('id', 'in', account_ids.ids)]
            rep_line.account_ids_domain = args
