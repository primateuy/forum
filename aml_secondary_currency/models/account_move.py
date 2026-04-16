# -*- coding: utf-8 -*-
from odoo import models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        res = super()._post(soft=soft)
        self.line_ids.compute_amount_secondary()
        return res