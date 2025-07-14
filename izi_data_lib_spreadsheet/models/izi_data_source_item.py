# -*- coding: utf-8 -*-
# Copyright 2022 IZI PT Solusi Usaha Mudah
from odoo import models, fields, api
from odoo.exceptions import UserError
import io
import pathlib
from io import StringIO, BytesIO
import pandas
import requests
import gspread
import base64
from oauth2client.service_account import ServiceAccountCredentials

file_code = '''
attachment = env['ir.attachment'].browse(%s)
if not attachment:
    izi.alert('Attachment Not Found')
try:
    kwargs = {
        'nrows': %s,
    }
    res_dataframe = izi.read_attachment_df(attachment, **kwargs)
    izi_table.get_table_fields_from_dataframe(res_dataframe)
except Exception as e:
    izi.alert(str(e))
'''

auth_google_sheet_code = '''
pandas = izi.lib('pandas')
try:
    spreadsheet = izi.get_authorized_gsheet('{google_sheet_id}', '{google_sheet_json_key_attachment_name}')
    worksheet_titles = [worksheet.title for worksheet in spreadsheet.worksheets()]
    if '{google_sheet_name}' not in worksheet_titles:
        izi.alert('Sheet Not Found')
    worksheet = spreadsheet.worksheet('{google_sheet_name}')
    data_with_header = worksheet.get_all_values()
    header = data_with_header[0]
    if {limit} >= 1:
        data = data_with_header[1:{limit}]
    else:
        data = data_with_header[1:]
    res_dataframe = pandas.DataFrame(data, columns=header)
    izi_table.get_table_fields_from_dataframe(res_dataframe)
except Exception as e:
    izi.alert(str(e))
'''
public_google_sheet_code = '''
pandas = izi.lib('pandas')
try:
    gsheet_url = "https://docs.google.com/spreadsheets/d/{google_sheet_id}/gviz/tq?tqx=out:csv&sheet={google_sheet_name}"
    res_dataframe = pandas.read_csv(gsheet_url, nrows={limit})
    izi_table.get_table_fields_from_dataframe(res_dataframe)
except Exception as e:
    izi.alert(str(e))
'''


class IZIDataSourceItem(models.Model):
    _inherit = 'izi.data.source.item'
    _description = 'IZI Data Source Item'

    type = fields.Selection(
        selection_add=[
            ('file', 'File CSV / XLS'),
            ('google_sheet', 'Google Sheet'),
        ], ondelete={'file': 'cascade', 'google_sheet':'cascade'})
    file_attachment_id = fields.Many2one('ir.attachment', string='File (Attachment)', domain=[('mimetype', 'in',
        ('application/vnd.ms-excel', 
        'text/csv', 
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'))])
    file_attachment = fields.Binary('File', required=False)
    file_attachment_name = fields.Char('Filename', required=False)
    google_sheet_id = fields.Char('Sheet ID', required=False)
    google_sheet_name = fields.Char('Sheet Name', required=False)
    google_sheet_json_key_attachment_id = fields.Many2one('ir.attachment', string='JSON Key File (Attachment)', required=False, domain=[('mimetype', '=',
        'application/json')])
    google_sheet_json_key_attachment = fields.Binary('JSON Key File', required=False)
    google_sheet_json_key_attachment_name = fields.Char('JSON Key Filename', required=False)

    @api.model
    def process_data_file(self, dashboard_id, file_name, file_type, file_content):
        res = {
            'status': 200,
        }
        try:
            source_item_name = ''
            if file_name and file_content:
                if file_type == 'text/csv':
                    file_content = file_content.encode('utf-8')
                    file_content = base64.b64encode(file_content)
                    file_content = file_content.decode('utf-8')
                attachment = self.env['ir.attachment'].create({
                    'name': file_name,
                    'datas': file_content,
                    'mimetype': file_type,
                    'type': 'binary',
                    'analytic': True,
                })
                source_item = self.create({
                    'name': file_name,
                    'type': 'file',
                    'file_attachment_id': attachment.id,
                })
                source_item.with_context(default_dashboard_id=dashboard_id).process_data()
        except Exception as e:
            return {
                'status': 500,
                'message': str(e),
            }
        return res

    def process_data(self):
        analysis = False
        dashboard = False
        if self._context.get('file_name'):
            self.name = str(self._context.get('file_name'))
        if self._context.get('default_dashboard_id'):
            dashboard_id = int(self._context.get('default_dashboard_id'))
            dashboard = self.env['izi.dashboard'].browse(dashboard_id)
            table = self.env['izi.table'].create({
                'name': self.name,
                'is_stored': True,
                'is_direct': True,
                'source_id': self.source_id.id,
                'stored_option': 'direct',
            })
            self.table_id = table.id
            analysis = self.env['izi.analysis'].create({
                'name': self.name,
                'method': 'table',
                'table_id': table.id,
            })
            block = self.env['izi.dashboard.block'].create({
                'analysis_id': analysis.id,
                'dashboard_id': dashboard.id,
            })

        if not self.table_id:
            table = self.env['izi.table'].create({
                'name': self.name,
                'is_stored': True,
                'is_direct': True,
                'source_id': self.source_id.id,
                'stored_option': 'direct',
            })
            self.table_id = table.id
        
        if self.table_id and self.table_id.cron_id and self.table_id.is_direct:
            if self.type == 'file':
                if self.file_attachment:
                    attachment = self.env['ir.attachment'].create({
                        'name': self.file_attachment_name,
                        'datas': self.file_attachment,
                        'analytic': True,
                    })
                    self.file_attachment_id = attachment.id
                if self.file_attachment_id:
                    self.table_id.cron_id.code = file_code % (self.file_attachment_id.id, self.limit)
                    self.table_id.method_direct_trigger()
                else:
                    raise UserError('File Not Found')
            elif self.type == 'google_sheet':
                if self.google_sheet_id and self.google_sheet_name:
                    if self.google_sheet_json_key_attachment:
                        attachment = self.env['ir.attachment'].create({
                            'name': self.google_sheet_json_key_attachment_name,
                            'datas': self.google_sheet_json_key_attachment,
                            'analytic': True,
                        })
                        self.google_sheet_json_key_attachment_id = attachment.id
                    if self.google_sheet_json_key_attachment_id:
                        self.table_id.cron_id.code = auth_google_sheet_code.format(**{
                            'google_sheet_id': self.google_sheet_id,
                            'google_sheet_name': self.google_sheet_name.replace(' ', '%20'),
                            'google_sheet_json_key_attachment_name': self.google_sheet_json_key_attachment_id.name,
                            'limit': self.limit,
                        })
                    else:
                        self.table_id.cron_id.code = public_google_sheet_code.format(**{
                            'google_sheet_id': self.google_sheet_id,
                            'google_sheet_name': self.google_sheet_name.replace(' ', '%20'),
                            'limit': self.limit,
                        })
                    self.table_id.method_direct_trigger()
                else:
                    raise UserError('Google Sheet URL and Sheet Name Must Be Filled!')
        else:
            raise UserError('The Table Must Use Direct Script!')

        if analysis and dashboard and self._context.get('default_dashboard_id'):
            analysis._set_default_metric()

        return True