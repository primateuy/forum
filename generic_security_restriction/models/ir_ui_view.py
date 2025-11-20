import json
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    def _get_merged_node_options(self, target_options, source_options):
        """
        Merge node-specific options with source options
        and return the resulting options string.

        This function takes the current node-specific options string
        and a dictionary of source options and merges these options together.

        Parameters:
            target_options (str):
            The existing node-specific options as a string.
            source_options (dict): A dictionary
            containing the source options to be merged.

        Returns:
            str: The merged options string containing
            both node-specific and source options.

        Example:
            target_options = "{'param1': 10, 'param2': 'value2'}"
            source_options = {'param3': True, 'param4': 'value4'}

            Resulting merged_options will be:
            "{'param1': 10, 'param2': 'value2',
            'param3': True, 'param4': 'value4'}"
        """
        source_options_str = ', '.join(
            "'{}': {!r}".format(str(key), value)
            for key, value in source_options.items()
        )

        insert_idx = target_options.rfind('}')
        options = "{},{},{}".format(
            target_options[:insert_idx], source_options_str,
            target_options[insert_idx:]
        )

        return options

    def _postprocess_tag_field(self, node, name_manager, node_info):

        result = super(IrUiView, self)._postprocess_tag_field(
            node, name_manager, node_info)

        model = self.env['ir.model']._get(name_manager.model._name)
        field_name = node.get('name')
        field_security = self.env['generic.security.restriction.field'].search(
            [('model_id', '=', model.id), ('field_name', '=', field_name)])

        if field_security:
            self.env.registry.clear_cache()
        if not self.env.user.groups_id & field_security.group_ids:
            return result

        if field_security.set_invisible:
            node.set('invisible', '1')
        if field_security.set_readonly:
            node.set('readonly', '1')
        if (field_security.field_type == 'many2one' and
                field_security.rewrite_options):
            restriction_options = {
                'no_open': field_security.set_no_open,
                'no_create': field_security.set_no_create,
                'no_quick_create':
                    field_security.set_no_quick_create,
                'no_create_edit': field_security.set_no_create_edit
            }
            # If node already has options, merge them with
            # restriction options
            if node.get('options'):
                node_option = node.get('options')
                merged_options = self._get_merged_node_options(
                    target_options=node_option,
                    source_options=restriction_options
                )
                node.set('options', merged_options)
            else:
                node.set('options',
                         json.dumps(restriction_options))
        return result

    def _postprocess_tag_button(self, node, name_manager, node_info):

        postprocessor = getattr(
            super(IrUiView, self), '_postprocess_tag_button', False)
        if postprocessor:
            super(IrUiView, self)._postprocess_tag_button(
                node, name_manager, node_info)

        fields_security = self.env['ir.model']._get(
            name_manager.model._name
        ).mapped('field_security_ids')

        fields_hide_stat_button = fields_security.search(
            [
                ('field_name', 'in',
                 [i.get('name') for i in node.iter(tag='field')]),
                ('hide_stat_button', '=', True)
            ]
        )

        if not self.env.user.groups_id & fields_hide_stat_button.group_ids:
            return None

        if fields_hide_stat_button:
            node.set('invisible', '1')

        return None
