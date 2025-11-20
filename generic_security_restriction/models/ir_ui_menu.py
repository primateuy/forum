import logging

from odoo import models, fields

_logger = logging.getLogger(__name__)


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    restrict_group_ids = fields.Many2many(
        'res.groups', 'ir_ui_menu_group_restrict_rel', 'menu_id', 'gres_id',
        string='Restricted Groups',
        help="If you have groups, the restrict of visibility of this menu"
             " will be based on these groups.")
    hide_from_user_ids = fields.Many2many(
        'res.users', 'ir_ui_menu_res_users_hidden_rel',
        'menu_id', 'user_id', string='Hidden menus')

    def _filter_visible_menus(self):
        menus = super(IrUiMenu, self)._filter_visible_menus()

        if self.env.su:
            return menus

        access_group_only_menus = self.env.user.mapped(
            'groups_id.menu_access_only')
        access_user_only_menus = self.env.user.access_only_menu_ids

        # Collect child action menus
        # The user settings has high priority then group settings
        # If menus met in user settings, only they will be applied
        allowed_child_menus = self.browse()
        if access_user_only_menus:
            allowed_child_menus += self.env['ir.ui.menu'].sudo().search([
                ('id', 'child_of', access_user_only_menus.ids)])
        elif access_group_only_menus and not access_user_only_menus:
            allowed_child_menus += self.env['ir.ui.menu'].sudo().search([
                ('id', 'child_of', access_group_only_menus.ids)])

        # Collect parents for action menus
        # to pass valid menu tree into JS
        if allowed_child_menus:
            allowed_parent_menus = self.env['ir.ui.menu'].sudo().search([
                ('id', 'parent_of', allowed_child_menus.ids)])
            visible_menus = allowed_parent_menus + allowed_child_menus

            # Filter to avoid return the menus,
            # that restricted by the user group odoo
            menus = menus.filtered(lambda menu: (menu in visible_menus))

        menus = menus.filtered(
            lambda menu: (
                menu not in self.env.user.mapped(
                    'groups_id.menu_access_restrict') and
                menu not in self.env.user.hidden_menu_ids))

        return menus
