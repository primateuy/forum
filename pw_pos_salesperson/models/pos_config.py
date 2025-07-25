# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class PosConfig(models.Model):
    _inherit = 'pos.config'

    allow_salesperson = fields.Boolean('Allow Salesperson')

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    allow_salesperson = fields.Boolean(related='pos_config_id.allow_salesperson',readonly=False)
