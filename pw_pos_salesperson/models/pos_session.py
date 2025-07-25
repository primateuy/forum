# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _loader_params_res_users(self):
        return {
            'search_params': {
                # 'domain': [('id', '=', self.env.user.id)],
                'domain': [('share', '=', False)],
                'fields': ['name', 'groups_id'],
            },
        }

    def _get_pos_ui_res_users(self, params):
        user = self.env['res.users'].search_read(**params['search_params'])[0]
        user['role'] = 'manager' if any(id == self.config_id.group_pos_manager_id.id for id in user['groups_id']) else 'cashier'
        del user['groups_id']
        # return user
        return self.env['res.users'].search_read(**params['search_params'])
