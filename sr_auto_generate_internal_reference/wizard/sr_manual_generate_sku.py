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


class srGenerateManualSku(models.TransientModel):
    _name = "sr.generate.manual.sku"

    is_replace_existing = fields.Boolean('Replace Existing?')
    product_name_digit = fields.Integer(string="Product Name Length")
    product_name_separate = fields.Char(string="Product Name Separator", size=1)

    product_attribute_digit = fields.Integer(string="Product Attribute Length")
    product_attribute_separate = fields.Char(string="Product Attribute Separator", size=1)

    product_category_digit = fields.Integer(string="Product Category Length")
    product_category_separate = fields.Char(string="Product Category Separator", size=1)

    @api.model
    def default_get(self,fields):
        res = super(srGenerateManualSku, self).default_get(fields)
        ICPSudo = self.env['ir.config_parameter'].sudo()
        res.update(
            product_name_digit=int(ICPSudo.get_param('product_name_digit', default=3)),
            product_name_separate=ICPSudo.get_param('product_name_separate', default='-'),
            product_attribute_digit=int(ICPSudo.get_param('product_attribute_digit', default=3)),
            product_attribute_separate=ICPSudo.get_param('product_attribute_separate', default='/'),
            product_category_digit=int(ICPSudo.get_param('product_category_digit', default=3)),
            product_category_separate=ICPSudo.get_param('product_category_separate', default='*')
        )
        return res


    def generate_manual_sku(self):
        product_ids = self.env[self._context.get('active_model')].browse(self._context.get('active_ids'))
        if self.is_replace_existing:
            for record in product_ids:
                final_internal_ref = ''
                final_internal_ref += record.name[:self.product_name_digit] + self.product_name_separate
                for line in record.product_template_attribute_value_ids:
                    final_internal_ref += line.name[:self.product_attribute_digit] + self.product_attribute_separate
                final_internal_ref += record.categ_id.name[:self.product_category_digit] + self.product_category_separate + str(
                    self.env["ir.sequence"].next_by_code("sr.auto.generate.sku.sequence"))
                record.write({
                    'default_code': final_internal_ref
                })
        else:
            for record in product_ids:
                final_internal_ref = ''
                if not record.default_code:
                    final_internal_ref += record.name[:self.product_name_digit] + self.product_name_separate
                    for line in record.product_template_attribute_value_ids:
                        final_internal_ref += line.name[:self.product_attribute_digit] + self.product_attribute_separate
                    final_internal_ref += record.categ_id.name[:self.product_category_digit] + self.product_category_separate + str(
                        self.env["ir.sequence"].next_by_code("sr.auto.generate.sku.sequence"))
                    record.write({
                        'default_code': final_internal_ref
                    })