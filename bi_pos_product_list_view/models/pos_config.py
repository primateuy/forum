# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
	

class PosConfiguration(models.Model):
	_inherit = 'pos.config'

	enable_list_view = fields.Boolean('Enable List View', default=True)
	display_product_name=fields.Boolean("Display Product Name", default=True)
	display_product_type=fields.Boolean("Display Product Type", default=True)
	display_product_code=fields.Boolean("Display Product Reference Code", default=True)
	display_product_image=fields.Boolean("Display Product Image", default=True)
	display_product_UOM=fields.Boolean("Display Product UOM", default=True)
	display_product_price=fields.Boolean("Display Product Price", default=True)
	display_product_on_hand_qty=fields.Boolean("Display Product On hand Qty", default=True)
	display_product_forecast_qty=fields.Boolean("Display Forecasted Qty", default=True)
	image_size = fields.Selection([
        ('small', 'Small Size'),
        ('medium', 'Medium Size'),
        ('large', 'Large'),],default='medium')
	prod_view = fields.Selection([
        ('list', 'List View'),
        ('grid', 'Grid View'),],default='grid')
	product_ordering = fields.Selection([
		('a_to_z', 'Sort Name A to Z'),
		('z_to_a', 'Sort Name Z to A'),
		('low_to_high', 'Sort From Low to High Sale Price'),
		('high_to_low', 'Sort From High to Low Sale Price'), ])


class ResConfigSettings(models.TransientModel):
	_inherit = 'res.config.settings'

	pos_enable_list_view = fields.Boolean(related='pos_config_id.enable_list_view',readonly=False)
	pos_display_product_name = fields.Boolean(related='pos_config_id.display_product_name',readonly=False)
	pos_display_product_type = fields.Boolean(related='pos_config_id.display_product_type',readonly=False)
	pos_display_product_code = fields.Boolean(related='pos_config_id.display_product_code',readonly=False)
	pos_display_product_image = fields.Boolean(related='pos_config_id.display_product_image',readonly=False)
	pos_display_product_UOM = fields.Boolean(related='pos_config_id.display_product_UOM',readonly=False)
	pos_display_product_price = fields.Boolean(related='pos_config_id.display_product_price',readonly=False)
	pos_display_product_on_hand_qty = fields.Boolean(related='pos_config_id.display_product_on_hand_qty',readonly=False)
	pos_display_product_forecast_qty = fields.Boolean(related='pos_config_id.display_product_forecast_qty',readonly=False)
	pos_image_size = fields.Selection(related='pos_config_id.image_size',readonly=False)
	pos_prod_view = fields.Selection(related='pos_config_id.prod_view',readonly=False)
	pos_product_ordering = fields.Selection(related='pos_config_id.product_ordering',readonly=False)


class POSSession(models.Model):
	_inherit = 'pos.session'

	def _loader_params_product_product(self):
		res = super(POSSession, self)._loader_params_product_product()
		fields = res.get('search_params').get('fields')
		fields.extend(['qty_available','virtual_available','default_code','list_price','name','uom_id','type'])
		res['search_params']['fields'] = fields
		return res