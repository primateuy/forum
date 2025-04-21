from odoo import api, fields, models, _


class AdvanceReorderingSettings(models.Model):
    _name = 'advance.reordering.settings'
    _description = 'Advance Reordering Settings'

    name= fields.Char(string="Name", default="Advance Reordering Configuration")
    reorder_rounding_method = fields.Selection([('round_up', 'Rounding up'), ('round_down', 'Rounding down')],
                                               string="Rounding Method",
                                               help="Rounding Method will be set rounding according to selected value")
    reorder_round_quantity = fields.Integer('Round Quantity')

    purchase_lead_calc_base_on = fields.Selection([('vendor_lead_time', 'Vendor Lead Time'),
                                                   ('real_time', 'Real Time'),
                                                   ('static_lead_time', 'Static Lead Time')
                                                   ], string="Purchase lead calculation base on",
                                                  help='Vendor lead time used product/purchase tab Vendor list lead '
                                                       'days time and real time lead is calculation base purchase order'
                                                       'date received - purchase order confirm date')

    max_lead_days_calc_method = fields.Selection([('max_lead_days', 'Actual Maximum Lead Time'),
                                                  ('avg_extra_percentage', 'Average + Extra Percentage')],
                                                 string='Max lead days calculation Method')
    extra_lead_percentage = fields.Float('Extra Percentage For Max Lead Days')

    max_sales_calc_method = fields.Selection([('max_daily_sales', 'Actual Maximum Daily Sales'),
                                              ('avg_extra_percentage', 'Average + Extra Percentage')],
                                             string='Max sales calculation Method')
    extra_sales_percentage = fields.Float('Extra Percentage For Max Sales')

    vendor_lead_days_method = fields.Selection([('max', 'Vendor Max lead days'),
                                                ('avg', 'Vendor Average lead days'),
                                                ('minimum', 'Vendor Minimum lead days'),
                                                ('static', 'static lead days')
                                                ], string='Vendor lead days calculation Method')
    vendor_static_lead_days = fields.Integer("Vendor Static Lead Days")

    @api.model
    def open_record_action(self):
        view_id = self.env.ref('setu_advance_reordering.advance_reordering_settings_view_form').id
        record = self.env['advance.reordering.settings'].search([]).id
        return {'type': 'ir.actions.act_window',
                'name': _('Settings - Advance Reordering'),
                'res_model': 'advance.reordering.settings',
                'target': 'current',
                'res_id': record,
                'view_mode': 'form',
                'views': [[view_id, 'form']],
                }