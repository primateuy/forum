import logging

from odoo import models, api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


class Base(models.AbstractModel):
    _inherit = 'base'

    @api.model
    def get_views(self, views, options=None):

        res = super(Base, self).get_views(
            views=views, options=options)

        if self._uid == SUPERUSER_ID:
            # This cache clear is needed here, because the method
            # '_postprocess_tag_field' not triggered
            self.env.registry.clear_cache('templates')
            return res

        for view in res['views']:

            if res['views'].get(view, {}).get('toolbar', {}).get('print', []):

                hidden_reports = self.env.user.hidden_reports_ids
                hidden_reports += self.env.user.groups_id.mapped(
                    'hidden_report_ids')

                new_print_actions = []
                for act in res['views'][view]['toolbar']['print']:

                    if act['id'] not in hidden_reports.ids:
                        # Remove field that contains user or groups
                        # restrictions to avoid passing it to js client.
                        act.pop('hide_for_user_ids', False)
                        act.pop('hide_for_group_ids', False)
                        new_print_actions += [act]
                res['views'][view]['toolbar']['print'] = new_print_actions

            # Remove restricted actions from view
            if res['views'].get(view, {}).get('toolbar', {}).get('action', []):

                hidden_actions = self.env.user.hidden_actions_ids
                hidden_actions += self.env.user.groups_id.mapped(
                    'hidden_actions_ids')
                # check hided server actions
                hidden_server_actions = self.env.user.hidden_server_actions_ids
                hidden_server_actions += self.env.user.groups_id.mapped(
                    'hidden_server_actions_ids')
                new_window_actions = []
                for act in res['views'][view]['toolbar']['action']:

                    if act['id'] not in (
                            hidden_actions.ids + hidden_server_actions.ids):
                        act.pop('restrict_group_ids', False)
                        act.pop('hide_from_user_ids', False)
                        new_window_actions += [act]
                res['views'][view]['toolbar']['action'] = new_window_actions

            if res['views'].get(view, {}).get('toolbar', {}).get('relate', []):

                hidden_actions = self.env.user.hidden_actions_ids
                hidden_actions += self.env.user.groups_id.mapped(
                    'hidden_actions_ids')
                # check hided server actions related
                hidden_server_actions = self.env.user.hidden_server_actions_ids
                hidden_server_actions += self.env.user.groups_id.mapped(
                    'hidden_server_actions_ids')
                new_related_actions = []
                for act in res['views'][view]['toolbar']['relate']:

                    if act['id'] not in (
                            hidden_actions.ids + hidden_server_actions.ids):
                        act.pop('restrict_group_ids', False)
                        act.pop('hide_from_user_ids', False)
                        new_related_actions += [act]
                res['views'][view]['toolbar']['relate'] = new_related_actions

        # This cache clear is needed here, because the method
        # '_postprocess_tag_field' not triggered
        self.env.registry.clear_cache('templates')
        return res
