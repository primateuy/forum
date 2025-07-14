# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) Sitaram Solutions (<https://sitaramsolutions.in/>).
#
#    For Module Support : info@sitaramsolutions.in  or Skype : contact.hiren1188
#
##############################################################################


from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    sku_code_generation_setting = fields.Boolean(
        string="On Product Create Auto Generate Product SKU/Default Code/Internal Reference", default=False,
        config_parameter='sku_code_generation_setting')

    product_name_digit = fields.Integer(string="Product Name Length", config_parameter='product_name_digit')
    product_name_separate = fields.Char(string="Product Name Separator", size=1,
                                        config_parameter='product_name_separate')

    product_attribute_digit = fields.Integer(string="Product Attribute Length",
                                             config_parameter='product_attribute_digit')
    product_attribute_separate = fields.Char(string="Product Attribute Separator", size=1,
                                             config_parameter='product_attribute_separate')

    product_category_digit = fields.Integer(string="Product Category Length", config_parameter='product_category_digit')
    product_category_separate = fields.Char(string="Product Category Separator", size=1,
                                            config_parameter='product_category_separate')


    @api.model
    def set_values(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'sr_auto_generate_internal_reference.sku_code_generation_setting', self.sku_code_generation_setting)
        self.env['ir.config_parameter'].sudo().set_param('sr_auto_generate_internal_reference.product_name_digit',
                                                         self.product_name_digit)
        self.env['ir.config_parameter'].sudo().set_param('sr_auto_generate_internal_reference.product_name_separate',
                                                         self.product_name_separate)
        self.env['ir.config_parameter'].sudo().set_param('sr_auto_generate_internal_reference.product_attribute_digit',
                                                         self.product_attribute_digit)
        self.env['ir.config_parameter'].sudo().set_param(
            'sr_auto_generate_internal_reference.product_attribute_separate', self.product_attribute_separate)
        self.env['ir.config_parameter'].sudo().set_param('sr_auto_generate_internal_reference.product_category_digit',
                                                         self.product_category_digit)
        self.env['ir.config_parameter'].sudo().set_param(
            'sr_auto_generate_internal_reference.product_category_separate', self.product_category_separate)
        super(ResConfigSettings, self).set_values()

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        ICPSudo = self.env['ir.config_parameter'].sudo()
        sku_code_generation_setting = ICPSudo.get_param('sku_code_generation_setting')
        product_name_digit = int(ICPSudo.get_param('product_name_digit', default=3))
        product_name_separate = ICPSudo.get_param('product_name_separate', default='-')
        product_attribute_digit = int(ICPSudo.get_param('product_attribute_digit', default=3))
        product_attribute_separate = ICPSudo.get_param('product_attribute_separate', default='/')
        product_category_digit = int(ICPSudo.get_param('product_category_digit', default=3))
        product_category_separate = ICPSudo.get_param('product_category_separate', default='*')
        res.update(
            sku_code_generation_setting=sku_code_generation_setting,
            product_name_digit=product_name_digit,
            product_name_separate=product_name_separate,
            product_attribute_digit=product_attribute_digit,
            product_attribute_separate=product_attribute_separate,
            product_category_digit=product_category_digit,
            product_category_separate=product_category_separate
        )
        return res
