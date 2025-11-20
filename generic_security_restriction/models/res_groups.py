from odoo import models, fields, api


class Groups(models.Model):
    _inherit = "res.groups"

    menu_access_restrict = fields.Many2many(
        'ir.ui.menu', 'ir_ui_menu_group_restrict_rel',
        'gres_id', 'menu_id', string='Restrict Access Menu')
    menu_access_only = fields.Many2many(
        'ir.ui.menu', 'ir_ui_menu_group_restrict_access_only_rel',
        'gres_id', 'menu_id', string='Access Only Menus',
        help='Only selected menus will be available for this group')
    hidden_report_ids = fields.Many2many(
        'ir.actions.report', 'ir_actions_report_res_groups_hidden_reports_rel',
        'group_id', 'report_id', string='Restrict Access Reoprts')
    hidden_actions_ids = fields.Many2many(
        'ir.actions.act_window',
        'ir_actions_act_window_res_groups_hidden_actions_rel',
        'group_id', 'act_window_id', string='Restrict Access Actions')
    hidden_server_actions_ids = fields.Many2many(
        'ir.actions.server',
        'ir_actions_server_res_groups_hidden_actions_rel',
        'group_id', 'act_server_id',
        string='Restrict Access Contextual Server Actions')
    model_restriction_ids = fields.Many2many(
        comodel_name='generic.security.model.restriction',
        relation='generic_security_model_restriction__group__rel',
        column1='group_id',
        column2='restriction_id',
        help="Apply specified access restrictions to this group.")
    allowed_use_debug_mode = fields.Boolean(
        help="Allow use debug mode to this group.")

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            self.env['ir.ui.menu'].clear_caches()
            if 'allowed_use_debug_mode' in values:
                self.env.registry.clear_cache()
            if 'users' in values:
                self.env.registry.clear_cache()
        return super(Groups, self).create(vals_list)

    def write(self, values):
        self.env['ir.ui.menu'].clear_caches()
        if 'allowed_use_debug_mode' in values:
            self.env.registry.clear_cache()
        if 'users' in values:
            self.env.registry.clear_cache()
        return super(Groups, self).write(values)
