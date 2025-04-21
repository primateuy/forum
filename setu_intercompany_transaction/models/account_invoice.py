from odoo import models, fields, api, _


class AccountMove(models.Model):
    _inherit = 'account.move'

    intercompany_transfer_id = fields.Many2one("setu.intercompany.transfer","Intercompany Transfer", copy=False, index=True)

