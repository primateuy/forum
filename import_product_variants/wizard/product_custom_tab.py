import xml.etree.ElementTree as ET
from odoo import models, fields, exceptions, api, tools, _


class IrGlobalCustomTabs(models.Model):
    _name = 'ir.global.tabs'
    _description = "Custom Global Tabs"

    def get_model(self):
        name = self._context.get('active_model')
        # sudo: lectura de ir.model para usuarios sin permiso admin.
        model_id = self.env['ir.model'].sudo().search([('model', '=', name)])
        return model_id

    name = fields.Char('Name', required=True)
    field_description = fields.Char('Tabs Label', required=True)
    model_id = fields.Many2one('ir.model', 'Model', required=True,  ondelete='cascade', default=get_model,
                               readonly=True, )
    view_id = fields.Many2one('ir.ui.view', string="View")

    def create_global_custome_tabs(self):

        model_id = self.env['ir.model'].sudo().search([('model', '=', self.model_id.model)], limit=1).model

        if self._context.get('active_model') == 'product.template':
            view_id = self.env['ir.ui.view'].sudo().search([('name', '=', 'product.template.product.form')])
        if self._context.get('active_model') == 'product.product':
            view_id = self.env['ir.ui.view'].sudo().search([('name', '=', 'product.product.form')])

        else:
            view_id = self.env['ir.ui.view'].sudo().search(
                [('model', '=', model_id), ('type', '=', 'form'), ('active', '=', True), ('inherit_id', '=', False)],
                limit=1)
        inherit_id = self.env.ref(view_id.xml_id)
        if view_id:
            custom_tab_string = ""
            custom_tab_string += "<?xml version='1.0'?>\n"
            custom_tab_string += "   <data>\n"
            custom_tab_string += "   <notebook>\n"
            custom_tab_string += "   		<page string= \"" + self.field_description + "\" name= \"" + self.name + "\"/>\n"
            custom_tab_string += "   </notebook>\n"
            custom_tab_string += "   </data>"

        required_tabs = self.env['ir.model.tabs'].sudo().search([('model_id', '=', self.model_id.id)])

        generated_view = self.env['ir.ui.view'].sudo().create({'name': 'global.custom.tabs',
                                                               'type': 'form',
                                                               'model': model_id,
                                                               'mode': 'extension',
                                                               'inherit_id': inherit_id.id,
                                                               'arch_base': custom_tab_string,
                                                               'active': True,
                                                               })
        self.env['ir.model.tabs'].sudo().create(
            {'model_id': self.model_id.id, 'tab_string': self.field_description, 'tab_name': self.name,
             'view_id': generated_view.id})
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }


class IrModelTabs(models.Model):
    _name = "ir.model.tabs"
    _rec_name = 'tab_string'
    _description = "IrModel tabs"

    tab_string = fields.Char(string="String")
    tab_name = fields.Char(string="Name")
    model_id = fields.Many2one('ir.model')
    position = fields.Integer(string="Position")
    view_id = fields.Many2one('ir.ui.view', string="Created view")
