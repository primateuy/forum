from odoo import fields, models, api, _


class ResPartner(models.Model):
    _inherit = 'res.partner'

    minimum_reorder_amount = fields.Monetary('Minimum Reorder Amount')
    vendor_rule = fields.Selection([('both', 'BOTH'),
                                    ('minimum_order_qty', 'Minimum Order Qty'),
                                    ('minimum_order_value', 'Minimum Order Value')],
                                   default='minimum_order_qty',
                                   string='Vendor Rule')
    vendor_pricelist_ids = fields.One2many("product.supplierinfo", "partner_id", "Vendor Pricelists")
