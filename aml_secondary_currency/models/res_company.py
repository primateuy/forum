# -*- coding: utf-8 -*-
from odoo import models, fields

class ResCompany(models.Model):
    _inherit = "res.company"

    # Activate the currency update
    secondary_currency_id = fields.Many2one(comodel_name='res.currency', string='Divisa secundaria')
