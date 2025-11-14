# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields,_
import base64


class POSOrder(models.Model):
    _inherit = 'pos.order'

    is_send = fields.Boolean(
        string='Is invoice send?',
    )

    def _generate_pos_order_invoice(self):
        moves = self.env['account.move']

        for order in self:
            # Force company for all SUPERUSER_ID action
            if order.account_move:
                moves += order.account_move
                continue

            if not order.partner_id:
                raise UserError(_('Please provide a partner for the sale.'))

            move_vals = order._prepare_invoice_vals()
            new_move = order._create_invoice(move_vals)

            order.write({'account_move': new_move.id, 'state': 'invoiced'})
            new_move.sudo().with_company(order.company_id).with_context(skip_invoice_sync=True)._post()

            moves += new_move
            payment_moves = order._apply_invoice_payments(order.session_id.state == 'closed')

            # Send and Print
            if not order.config_id.auto_check_invoice and not order.config_id.auto_print_invoice == 'allow_auto_print_invoice':
                if self.env.context.get('generate_pdf', True):
                    template = self.env.ref(new_move._get_mail_template())
                    new_move.with_context(skip_invoice_sync=True)._generate_pdf_and_send_invoice(template)


            if order.session_id.state == 'closed':  # If the session isn't closed this isn't needed.
                # If a client requires the invoice later, we need to revers the amount from the closing entry, by making a new entry for that.
                order._create_misc_reversal_move(payment_moves)

        if not moves:
            return {}

        return {
            'name': _('Customer Invoice'),
            'view_mode': 'form',
            'view_id': self.env.ref('account.view_move_form').id,
            'res_model': 'account.move',
            'context': "{'move_type':'out_invoice'}",
            'type': 'ir.actions.act_window',
            'target': 'current',
            'res_id': moves and moves.ids[0] or False,
        }


    def send_mail_invoice(self):
        if not self.account_move:
            self.action_pos_order_invoice()
        template = self.env.ref('pos_invoice_auto_check.mail_template')
        email_values = {
            'email_to': self.partner_id.email,
            'email_from': self.env.user.partner_id.email,
        }
        invoice_attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'account.move'),
            ('res_id', '=', self.account_move.id)])
        if not invoice_attachment:
            invoice = self.env['ir.actions.report']._render_qweb_pdf(
                "account.account_invoices", self.account_move.id)
            invoice_report = base64.b64encode(invoice[0])
            values = {
                'name': "Invoice" + self.name,
                'type': 'binary',
                'datas': invoice_report,
                'store_fname': invoice_report,
                'mimetype': 'application/pdf',
            }
            invoice_attachment = self.env['ir.attachment'].sudo().create(
                values)
        template.attachment_ids = [(6, 0, [invoice_attachment.id])]
        self.env['mail.template'].browse(template.id).send_mail(
            self.id, email_values=email_values, force_send=True)
        self.is_send = True
        return True
