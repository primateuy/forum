from odoo import _, api, fields, models


class InheritedLocation(models.Model):
    _inherit = "stock.location"

    boolean_location_flag = fields.Boolean(string='Boolean Flag',default=False)
