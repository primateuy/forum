from odoo import models, fields, api, tools


class ResUsers(models.Model):
    _inherit = 'res.users'

    hidden_menu_ids = fields.Many2many(
        'ir.ui.menu', 'ir_ui_menu_res_users_hidden_rel',
        'user_id', 'menu_id', string='Hidden menus')
    access_only_menu_ids = fields.Many2many(
        'ir.ui.menu', 'ir_ui_menu_res_users_access_only_rel',
        'user_id', 'menu_id', string='Access only menus',
        help='Only selected menus will be available for this user')
    hidden_reports_ids = fields.Many2many(
        'ir.actions.report', 'ir_actions_report_res_users_hidden_reports_rel',
        'user_id', 'report_id', string='Hidden print reports')
    hidden_actions_ids = fields.Many2many(
        'ir.actions.act_window',
        'ir_actions_act_window_res_users_hidden_actions_rel',
        'user_id', 'act_window_id', string='Hidden actions')
    hidden_server_actions_ids = fields.Many2many(
        'ir.actions.server',
        'ir_actions_server_res_users_hidden_actions_rel',
        'user_id', 'act_server_id', string='Hidden contextual server actions')
    model_restriction_ids = fields.Many2many(
        comodel_name='generic.security.model.restriction',
        relation='generic_security_model_restriction__user__rel',
        column1='user_id',
        column2='restriction_id')
    allowed_use_debug_mode = fields.Boolean(
        help="Allow use debug mode for this user.")

    @api.model_create_multi
    def create(self, vals_list):
        users = super(ResUsers, self).create(vals_list)
        for user in users:
            self.env['ir.ui.menu'].clear_caches()
            if 'allowed_use_debug_mode' in user:
                self.env.registry.clear_cache()
            if 'groups_id' in user:
                self.env.registry.clear_cache()
        return users

    def write(self, values):
        res = super(ResUsers, self).write(values)
        self.env['ir.ui.menu'].clear_caches()
        if 'allowed_use_debug_mode' in values:
            self.env.registry.clear_cache()
        if 'groups_id' in values:
            self.env.registry.clear_cache()
        return res

    @api.model
    @tools.ormcache('user_id')
    def _gsr_is_debug_mode_allowed(self, user_id):
        user = self.sudo().browse(user_id)
        if user.allowed_use_debug_mode:
            return True
        # Check if allowed debug mode by groups
        if bool(user.groups_id.filtered(
                lambda g: g.allowed_use_debug_mode)):
            return True
        return False
