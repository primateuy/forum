from odoo import api, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.onchange('date', 'currency_id', 'journal_id', 'partner_id', 'invoice_line_ids')
    def _change_payable_receivable_account(self):
        for move in self:
            account_id = move.journal_id.account_currency_ids.filtered(
                lambda l: l.currency_id == move.currency_id
            ).account_id
            currency_account_receivable = (
                move.partner_id.property_account_receivable_id.currency_id.id
                if move.partner_id and move.partner_id.property_account_receivable_id.currency_id
                else move.env.company.currency_id.id
            )
            if move.move_type in ['out_refund', 'out_invoice'] and move.currency_id.id == currency_account_receivable:
                account_id = move.partner_id.property_account_receivable_id
    
            currency_account_payable = (
                move.partner_id.property_account_payable_id.currency_id.id
                if move.partner_id and move.partner_id.property_account_payable_id.currency_id
                else move.env.company.currency_id.id
            )
            if move.move_type in ['in_refund', 'in_invoice'] and move.currency_id.id == currency_account_payable:
                account_id = move.partner_id.property_account_payable_id
    
            if account_id and move.journal_id.type != 'general':
                lines = move.line_ids.filtered(
                    lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable')
                )
                if lines:
                    lines.write({'account_id': account_id.id})

    def action_post(self):
        """ Before validate invoice change account for line with account_type in ('asset_receivable', 'liability_payable')"""
        self._change_payable_receivable_account()
        res = super().action_post()
        return res
    
    @api.model_create_multi
    def create(self, vals_list):
        """After create, ajustar cuentas de líneas por cobrar/pagar."""
        moves = super().create(vals_list)
        # Llamar por registro para evitar singleton
        for move in moves:
            move._change_payable_receivable_account()
        return moves


