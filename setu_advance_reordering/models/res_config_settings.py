from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    approval_system_for_reorder = fields.Boolean('Approval System for Reorder',
                                                 help="Set true for Approved System to use Advance "
                                                      "Reorder Process")
    reorder_rounding_method = fields.Selection([('round_up', 'Rounding up'), ('round_down', 'Rounding down')],
                                               string="Rounding Method",
                                               help="Rounding Method will be set rounding according to selected value")
    reorder_round_quantity = fields.Integer('Round Quantity')

    purchase_lead_calc_base_on = fields.Selection([('vendor_lead_time', 'Vendor Lead Time'),
                                                   ('real_time', 'Real Time'),
                                                   ('static_lead_time', 'Static Lead Time')
                                                   ], string="Purchase lead calculation base on",
                                                  config_parameter='setu_advance_reordering.purchase_lead_calc_base_on',
                                                  help='Vendor lead time used product/purchase tab Vendor list lead '
                                                       'days time and real time lead is calculation base purchase order'
                                                       'date received - purchase order confirm date')

    max_lead_days_calc_method = fields.Selection([('max_lead_days', 'Actual Maximum Lead Time'),
                                                  ('avg_extra_percentage', 'Average + Extra Percentage')],
                                                 config_parameter='setu_advance_reordering.max_lead_days_calc_method',
                                                 string='Max lead days calculation Method')
    extra_lead_percentage = fields.Float('Extra Percentage For Max Lead Days',
                                         config_parameter='setu_advance_reordering.extra_lead_percentage', )

    max_sales_calc_method = fields.Selection([('max_daily_sales', 'Actual Maximum Daily Sales'),
                                              ('avg_extra_percentage', 'Average + Extra Percentage')],
                                             config_parameter='setu_advance_reordering.max_sales_calc_method',
                                             string='Max sales calculation Method')
    extra_sales_percentage = fields.Float('Extra Percentage For Max Sales',
                                          config_parameter='setu_advance_reordering.extra_sales_percentage', )

    vendor_lead_days_method = fields.Selection([('max', 'Vendor Max lead days'),
                                                ('avg', 'Vendor Average lead days'),
                                                ('minimum', 'Vendor Minimum lead days'),
                                                ('static', 'static lead days')
                                                ], string='Vendor lead days calculation Method',
                                               config_parameter='setu_advance_reordering.vendor_lead_days_method')
    vendor_static_lead_days = fields.Integer("Vendor Static Lead Days",
                                             config_parameter='setu_advance_reordering.vendor_static_lead_days')

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        approval_system_for_reorder = self.env['ir.config_parameter'].sudo(). \
            get_param('setu_advance_reordering.approval_system_for_reorder', False)
        reorder_rounding_method = self.env['ir.config_parameter'].sudo(). \
            get_param('setu_advance_reordering.reorder_rounding_method', False)
        reorder_round_quantity = self.env['ir.config_parameter'].sudo(). \
            get_param('setu_advance_reordering.reorder_round_quantity', False)
        res.update(approval_system_for_reorder=approval_system_for_reorder,
                   reorder_rounding_method=reorder_rounding_method,
                   reorder_round_quantity=reorder_round_quantity)
        return res

    @api.model
    def set_values(self):
        self.env['ir.config_parameter'].sudo().set_param('setu_advance_reordering.approval_system_for_reorder',
                                                         self.approval_system_for_reorder or False)
        self.env['ir.config_parameter'].sudo().set_param('setu_advance_reordering.reorder_rounding_method',
                                                         self.reorder_rounding_method or False)
        self.env['ir.config_parameter'].sudo().set_param('setu_advance_reordering.reorder_round_quantity',
                                                         self.reorder_round_quantity or False)
        super(ResConfigSettings, self).set_values()
