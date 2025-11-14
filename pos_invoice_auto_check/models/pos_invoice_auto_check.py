# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models, api, _
from datetime import date, time, datetime


class pos_config(models.Model):
    _inherit = 'pos.config'

    auto_check_invoice = fields.Boolean(string='Invoice Auto Check')
    auto_print_invoice = fields.Selection([
        ('allow_auto_print_invoice', 'Allow Auto Print Invoice'),
        ('disallow_auto_print_invoice', 'Disallow Auto Print invoice')],
        string='Auto Print Invoice', default="allow_auto_print_invoice", store=True)

    email_operation = fields.Selection(selection=[
        ('download', 'Download'),
        ('send', 'Send By Email'),
        ('download_send_email', 'Download & Send By Email')
    ], default="download_send_email", string='Button Operation')
    interval = fields.Integer(
        string='Interval',
    )
    email_period = fields.Selection(selection=[
        ('minutes', 'Minute'),
        ('hours', 'Hour'),
        ('days', 'Day'),
        ('weeks', 'Week'),
        ('months', 'Month')
    ], default="days", string='Period')

    start_email_service = fields.Boolean(default=False)
    close_email_service = fields.Boolean(default=True)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    auto_check_invoice = fields.Boolean(
        related='pos_config_id.auto_check_invoice', readonly=False)
    auto_print_invoice = fields.Selection(
        related='pos_config_id.auto_print_invoice', readonly=False)
    email_operation = fields.Selection(
        related='pos_config_id.email_operation', readonly=False)
    interval = fields.Integer(related='pos_config_id.interval', readonly=False)
    email_period = fields.Selection(
        related='pos_config_id.email_period', readonly=False)
    start_email_service = fields.Boolean(
        related='pos_config_id.start_email_service', readonly=False)
    close_email_service = fields.Boolean(
        related='pos_config_id.close_email_service', readonly=False)

    def start_mail_cron(self):
        self.pos_config_id.start_email_service = True
        self.pos_config_id.close_email_service = False
        mail_cron = self.env.ref(
            'pos_invoice_auto_check.send_invoice')
        mail_cron.active = True
        mail_cron.write({
            'interval_number': self.interval,
            'interval_type': self.email_period,
            'numbercall': -1,
            'code': 'model._send_mail(%s)' % (self.id)
        })

    def stop_mail_cron(self):
        self.pos_config_id.start_email_service = False
        self.pos_config_id.close_email_service = True
        mail_cron = self.env.ref(
            'pos_invoice_auto_check.send_invoice')
        mail_cron.write({
            'active': False,
        })

    def _send_mail(self, config):
        pos_config = self.env['res.config.settings'].browse(config)
        for order in pos_config.pos_config_id.mapped('session_ids').mapped('order_ids').filtered(lambda x: x.state == 'invoiced' and not x.is_send):
            order.send_mail_invoice()
