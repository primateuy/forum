# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.
from lxml import etree
from xml.dom import minidom
import xml.etree.ElementTree as ET
import types
import re
from odoo import fields, models, api, tools, _
from odoo.exceptions import UserError, ValidationError



class IrModelSelectionFieldInherit(models.Model):
    """docstring for IrModelFieldInherit"""

    _name = "ir.model.fields.selection.product"
    _description = "IrModel Selection Field"

    fields_id = fields.Many2one('ir.models.fields.custom')
    field = fields.Many2one('ir.model.fields')
    value = fields.Char(string="Value")
    name = fields.Char(string="name")


class IrModelsFieldsCustom(models.Model):
    _name = 'ir.models.fields.custom'
    _description = "Custom Global Fields"
    _inherit = 'ir.model.fields'

    def _get_fields_type(self):
        res = [('binary', 'binary'), ('boolean', 'boolean'), ('char', 'char'), ('date', 'date'),
               ('datetime', 'datetime'), ('float', 'float'), ('html', 'html'), ('integer', 'integer'),
               ('many2one', 'many2one'), ('many2many', 'many2many'), ('selection', 'selection'), ('text', 'text')]
        return res

    @api.onchange('required', 'ttype', 'on_delete')
    def _onchange_required(self):
        res = super(IrModelsFieldsCustom, self)._onchange_required()
        # for rec in self:
        #     if :
        #         return {'warning': {'title': _("Warning"), 'message': _(
        #             "The m2o field %s is required but declares its ondelete policy "
        #             "as being 'set null'. Only 'cascade' and 'cascade' make sense.", rec.name,
        #         )}}
        return False

    def get_model(self):
        name = self._context.get('active_model')
        model_id = self.env['ir.model'].search([('model', '=', name)])
        return model_id

    name = fields.Char('Field Name', required=True, default='x_')
    field_description = fields.Char('Field Label')
    model_id = fields.Many2one('ir.model', 'Model', required=True, ondelete='cascade', default=get_model,
                               domain=lambda self: [('model', '=', self.env.context.get('active_model'))])
    ttype = fields.Selection(_get_fields_type, 'Field Type', required=True)
    help = fields.Text(string='Field Help', translate=True)
    required = fields.Boolean(string='Required')
    readonly = fields.Boolean(string='Readonly')
    copied = fields.Boolean(string='Copied')
    groups = fields.Many2many('res.groups', 'global_custom_group_rel', 'custom_ids', 'group_id')
    selection_ids = fields.One2many("ir.model.fields.selection.product", "fields_id",
                                    string="Selection Options", copy=True)
    state = fields.Char('State', default='manual')
    relation = fields.Char(string="Relation")
    model_field = fields.Char('Model Field', related='relation')
    where_to_add = fields.Selection([('after', 'After'), ('before', 'Before')], string="Where to Add")
    after_which_field = fields.Many2one('ir.model.fields')
    domain = fields.Text(default='[]')
    domain_list = fields.Char(string="Based on Field", help="Coupon program will work for selected customers only")
    tab_list = fields.Many2one('ir.model.tabs', domain="[('model_id.id', '=',model_id)]", string="Tab List")
    view_id = fields.Many2one('ir.ui.view', string="View")

    @api.onchange('tab_list')
    def change_field_vals(self):
        if self.tab_list:
            self.update({'after_which_field': False})

    @api.onchange('after_which_field')
    def change_tab_vals(self):
        if self.after_which_field:
            self.update({'tab_list': False})

    @api.onchange('model_id')
    def field_domain(self):
        if self.model_id:
            model_name = self.model_id.model

            if model_name == 'product.template':
                view_id = self.env.ref('product.product_template_only_form_view')
            if model_name == 'product.product':
                view_id = self.env.ref('product.product_normal_form_view')

            else:
                view_id = self.env['ir.ui.view'].sudo().search(
                    [('model', '=', model_name), ('type', '=', 'form'), ('active', '=', True),
                     ('inherit_id', '=', False)], limit=1)

            if view_id:
                fields = []
                view_architecture = str(view_id.arch_base)
                document = ET.fromstring(view_architecture)
                for tag in document.findall('.//field'):
                    fields.append(tag.attrib['name'])

                return {
                    'domain': {'after_which_field': [('name', 'in', fields), ('model_id.id', '=', self.model_id.id)]}}

    @api.onchange('ttype', 'relation')
    def domain_fields(self):
        if self.ttype == 'many2one':
            if self.relation:
                return {'domain': {'domain_list': [('model', '=', self.relation)]}}

    @api.model
    def default_get(self, fields):
        res = super(IrModelsFieldsCustom, self).default_get(fields)
        all_models = self.env['ir.model'].sudo().search([])
        for model in all_models:
            model_name = model.model
            if model_name == 'product.template':
                view_id = self.env['ir.ui.view'].sudo().search([('name', '=', 'product.template.product.form')])
            if model_name == 'product.product':
                view_id = self.env['ir.ui.view'].sudo().search([('name', '=', 'product.product.form')])
            else:
                view_id = self.env['ir.ui.view'].sudo().search(
                    [('model', '=', model_name), ('type', '=', 'form'), ('active', '=', True),
                     ('inherit_id', '=', False)], limit=1)
            if view_id:
                for view in view_id:
                    view_architecture = str(view.arch_base)
                    document = ET.fromstring(view_architecture)
                    pos = 1
                    for tag in document.findall('.//page'):
                        if tag.attrib.get('string'):
                            tab = self.env['ir.model.tabs'].sudo().search(
                                [('tab_string', '=', tag.attrib['string']), ('model_id', '=', model.id)])
                        if tab:
                            pass
                        else:
                            if tag.attrib.get('string'):
                                string = tag.attrib['string']
                                self.env['ir.model.tabs'].sudo().create(
                                    {'tab_string': string, 'model_id': model.id, 'position': pos})
                                pos += 1

        return res

    def create_global_custome_field(self):
        custom_field_string = None
        if self._context.get('active_model') == 'product.template':
            ir_model_pool = self.env['ir.model']
            model_id = ir_model_pool.search([('model', '=', 'product.template')])
        if self._context.get('active_model') == 'product.product':
            ir_model_pool = self.env['ir.model']
            model_id = ir_model_pool.search([('model', '=', 'product.product')])
        field = self.env['ir.model.fields'].sudo().create({'name': self.name,
                                                           'field_description': self.field_description,
                                                           'model_id': model_id.id,
                                                           'ttype': self.ttype,
                                                           'relation': self.relation,
                                                           'index': self.index,
                                                           'store': self.store,
                                                           'help': self.help,
                                                           'readonly': self.readonly,
                                                           'copied': self.copied,
                                                           'domain': self.domain_list,
                                                           'state': 'manual',
                                                           })
        selection_model = self.env['ir.model.fields.selection']
        if not self.selection_ids and self.ttype == 'selection':
            raise UserError('Please Add values for selection')

        if self.selection_ids:
            for rec in self.selection_ids:
                selection = selection_model.sudo().create({'field_id': field.id, 'name': rec.name, 'value': rec.value})

        model = self.env['ir.model'].sudo().search([('model', '=', model_id.model)], limit=1).model
        if model == 'product.template':
            view_id = self.env['ir.ui.view'].sudo().search([('name', '=', 'product.template.product.form')])
        if model == 'product.product':
            view_id = self.env['ir.ui.view'].sudo().search([('name', '=', 'product.product.form')])

        else:
            view_id = self.env['ir.ui.view'].sudo().search(
                [('model', '=', model), ('type', '=', 'form'), ('active', '=', True), ('inherit_id', '=', False)],
                limit=1)
        inherit_id = self.env.ref(view_id.xml_id)
        if not self.tab_list and not self.after_which_field:
            raise UserError("Please add Tab list value or after which field value.")

        if self.tab_list and not self.after_which_field:
            view_arch = str(view_id.arch_base)
            doc = ET.fromstring(view_arch)
            count = 1
            for tag in doc.findall('.//page'):
                if not self.tab_list.tab_name:
                    if tag.attrib.get('string') == self.tab_list.tab_string:
                        custom_field_string = ""
                        custom_field_string += "<?xml version='1.0'?>\n"
                        custom_field_string += "   <data>\n"
                        custom_field_string += "      <xpath expr=\"//notebook/page[" + str(
                            count) + "]\" position=\"inside\">\n"
                        custom_field_string += "      <group>\n"
                        custom_field_string += "      	<group>\n"
                        custom_field_string += "        	<field string= \"" + self.field_description + "\" name=\"" + self.name + "\" ttype=\"" + self.ttype + "\"/>\n"
                        custom_field_string += "      	</group>\n"
                        custom_field_string += "      </group>\n"
                        custom_field_string += "     </xpath>\n"
                        custom_field_string += "   </data>\n"
                    count += 1
            if self.tab_list.tab_name:
                custom_field_string = ""
                custom_field_string += "<?xml version='1.0'?>\n"
                custom_field_string += "   <data>\n"
                custom_field_string += "      <page name= \"" + self.tab_list.tab_name + "\" position=\"inside\">\n"
                custom_field_string += "      <group>\n"
                custom_field_string += "      	<group>\n"
                custom_field_string += "   		<field string= \"" + self.field_description + "\" name=\"" + self.name + "\" ttype=\"" + self.ttype + "\"/>\n"
                custom_field_string += "      	</group>\n"
                custom_field_string += "      </group>\n"
                custom_field_string += "   	 </page>\n"
                custom_field_string += "   </data>"
        else:
            if self.after_which_field.name and self.where_to_add:
                custom_field_string = ""
                custom_field_string += "<?xml version='1.0'?>\n"
                custom_field_string += "   <data>\n"
                custom_field_string += "   	<field name=\"" + self.after_which_field.name + "\" position=\"" + self.where_to_add + "\">\n"
                custom_field_string += "   		<field name=\"" + self.name + "\" ttype=\"" + self.ttype + "\"/>\n"
                custom_field_string += "    </field>\n"
                custom_field_string += "   </data>\n"

        if custom_field_string:
            created_view = self.env['ir.ui.view'].sudo().create({'name': 'global.custom.fields',
                                                                 'type': 'form',
                                                                 'model': model,
                                                                 'mode': 'extension',
                                                                 'inherit_id': inherit_id.id,
                                                                 'arch_base': custom_field_string,
                                                                 'active': True,
                                                                 'groups_id': [(6, 0, self.groups.ids)], })

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',

        }
