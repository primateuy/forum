from odoo import fields, models, api, _


class SetuInterCompanyTransfer(models.Model):
    _inherit = 'setu.intercompany.transfer'

    procurement_warehouse_id = fields.Many2one('advance.procurement.process', string='Warehouse for Procurement', copy=False)
    procurement_company_id = fields.Many2one('advance.procurement.process', string='Warehouse for Company', copy=False)
