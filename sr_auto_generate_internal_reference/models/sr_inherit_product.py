# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) Sitaram Solutions (<https://sitaramsolutions.in/>).
#
#    For Module Support : info@sitaramsolutions.in  or Skype : contact.hiren1188
#
##############################################################################


from odoo import api, fields, models, _


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model
    def create(self,vals):
        res = super(ProductProduct, self).create(vals)
        ICPSudo = self.env['ir.config_parameter'].sudo()
        sku_code_generation_setting = ICPSudo.get_param('sku_code_generation_setting')
        final_internal_ref = ''
        if sku_code_generation_setting:
            final_internal_ref += res.name[:int(ICPSudo.get_param('product_name_digit'))] + ICPSudo.get_param('product_name_separate')
            for line in res.product_template_attribute_value_ids:
                final_internal_ref += line.name[:int(ICPSudo.get_param('product_attribute_digit'))] + ICPSudo.get_param('product_attribute_separate')
            final_internal_ref += res.categ_id.name[:int(ICPSudo.get_param('product_category_digit'))] + ICPSudo.get_param('product_category_separate') + str(self.env["ir.sequence"].next_by_code("sr.auto.generate.sku.sequence"))
            res.write({
                'default_code': final_internal_ref
            })
        return res