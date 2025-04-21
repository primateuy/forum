from odoo import models, fields, api, _

class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model_create_multi
    def create(self, vals_list):

        for vals in vals_list:
            vals.update({"company_id": False})
        res = super(ProductProduct, self).create(vals_list)
        return res
