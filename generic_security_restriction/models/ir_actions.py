from odoo import models, fields


class IrActions(models.Model):
    _inherit = 'ir.actions.act_window'

    restrict_group_ids = fields.Many2many(
        'res.groups', 'ir_actions_act_window_res_groups_hidden_actions_rel',
        'act_window_id', 'group_id',
        string='Restricted Groups',
        help="If you have groups, the restrict of visibility of this action"
             " will be based on these groups.")
    hide_from_user_ids = fields.Many2many(
        'res.users', 'ir_actions_act_window_res_users_hidden_actions_rel',
        'act_window_id', 'user_id', string='Hidden actions')


class IrActionsServer(models.Model):
    _inherit = 'ir.actions.server'

    restrict_group_ids = fields.Many2many(
        'res.groups', 'ir_actions_server_res_groups_hidden_actions_rel',
        'act_server_id', 'group_id',
        string='Restricted Groups',
        help="If you have groups, the restrict of visibility "
             "of this contextual server action will be based on these groups.")
    hide_from_user_ids = fields.Many2many(
        'res.users', 'ir_actions_server_res_users_hidden_actions_rel',
        'act_server_id', 'user_id', string='Hidden contextual server actions')
