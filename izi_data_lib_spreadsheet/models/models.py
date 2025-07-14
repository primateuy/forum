from odoo import models, fields, api, _
from odoo.exceptions import UserError
import io
import pathlib
from io import StringIO, BytesIO
import json
import pandas
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials

class IZITools(models.TransientModel):
    _inherit = 'izi.tools'

    @api.model
    def lib(self, key):
        lib = {
            'pandas': pandas,
            'requests': requests,
            'gspread': gspread,
        }
        if key in lib:
            return lib[key]
        return super(IZITools, self).lib(key)
    
    @api.model
    def requests(self, method, url, headers={}, data={}):
        response = requests.request(method, url=url, headers=headers, data=data)
        return response

    @api.model
    def requests_io(self, method, url, headers={}, data={}):
        response = requests.request(method, url=url, headers=headers, data=data)
        return io.StringIO(response.content.decode('utf-8'))
    
    @api.model
    def read_csv(self, url, **kwargs):
        data = []
        try:
            df = pandas.read_csv(
                url,
                **kwargs
            )
            data = df.to_dict('records')
        except Exception as e:
            raise UserError(str(e))
        return data
    
    @api.model
    def read_excel(self, url, **kwargs):
        data = []
        try:
            df = pandas.read_excel(
                url,
                **kwargs
            )
            data = df.to_dict('records')
        except Exception as e:
            raise UserError(str(e))
        return data

    @api.model
    def insert_in_odoo_spreadsheet(self, spreadsheet_name, data):
        self.check_su()
        try:
            df = pandas.DataFrame(data)
            in_memory_fp = io.BytesIO()
            df.to_excel(in_memory_fp, index=False, engine='xlsxwriter')
            excel_raw = in_memory_fp.getvalue()
            spreadsheet_folder = self.env.ref('documents_spreadsheet.documents_spreadsheet_folder')
            if spreadsheet_folder:
                document = self.env['documents.document'].create({
                    'name': spreadsheet_name,
                    'raw': excel_raw,
                    'folder_id': spreadsheet_folder.id,
                    'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                })
            
        except Exception as e:
            raise UserError(str(e))
        return True

    @api.model
    def read_from_odoo_spreadsheet(self, spreadsheet_name, sheet_name=False, start_cell=False, end_cell=False):
        self.check_su()
        res = False
        spreadsheet_folder = self.env.ref('documents_spreadsheet.documents_spreadsheet_folder')
        if spreadsheet_folder:
            document = self.env['documents.document'].search([('name', '=', spreadsheet_name), ('folder_id', '=', spreadsheet_folder.id)], limit=1)
        if not document:
            raise UserError('Spreadsheet not found.')
        if not (document and document.mimetype == 'application/o-spreadsheet' and document.raw):
            raise UserError('Document is found but not in odoo spreadsheet format. Please open the file in documents and do snapshot to get the latest data.')
        try:
            # Odoo Spreadsheet
            try:
                res = document._get_spreadsheet_snapshot()
                cells = {}
                if res.get('sheets'):
                    if sheet_name:
                        for sheet in res['sheets']:
                            if sheet['name'] == sheet_name:
                                cells = sheet['cells']
                    elif len(res['sheets']) > 0:
                        cells = res['sheets'][0]['cells']
                else:
                    raise UserError('Document is found but not in odoo spreadsheet format. Please open the file in documents and do snapshot to get the latest data.')
                # cells = {'A1': {'content': 'id'}, 'A2': {'content': '1'}, 'A3': {'content': '2'}, 'B1': {'content': 'name'}, 'B2': {'content': 'Product 1'}, 'B3': {'content': 'Product 2'}}
                # res = [{'id': 1, 'name': 'Product 1'}, {'id': 2, 'name': 'Product 2'}]
                # Convert Cells to Res (List of Dict)
                # Get The Row Header
                # start_cell = 'A1'
                if start_cell:
                    header_row = int(start_cell[1:])
                    start_col = ord(start_cell[0].upper()) - 64
                else:
                    header_row = False
                    start_col = False
                    for cell in cells:
                        row = int(cell[1:])
                        col = ord(cell[0].upper()) - 64
                        if cells[cell].get('content'):
                            if not header_row or row < header_row:
                                header_row = row
                            if not start_col or col < start_col:
                                start_col = col

                # Header
                start_row = header_row + 1
                cur_row = header_row
                cur_col = start_col
                field_by_col = {}
                while(True):
                    cell = chr(cur_col + 64) + str(cur_row)
                    if cells.get(cell) and cells.get(cell).get('content'):
                        field_by_col[cur_col] = cells[cell]['content']
                    else:
                        break
                    cur_col += 1
                end_col = cur_col
                
                # Data
                cur_row = start_row
                cur_col = start_col
                res = []
                while(True):
                    row_data = {}
                    # Check The First Col
                    cur_col = start_col
                    cell = chr(cur_col + 64) + str(cur_row)
                    if cells.get(cell) and cells.get(cell).get('content'):
                        content = cells[cell]['content']
                        # If Exist. Create Row Data Dict, Get Other Col, And Append To Res
                        if content:
                            row_data = {}
                            row_data[field_by_col[cur_col]] = content
                            cur_col += 1
                            while cur_col < end_col:
                                cell = chr(cur_col + 64) + str(cur_row)
                                if cells.get(cell) and cells.get(cell).get('content'):
                                    content = cells[cell]['content']
                                    if field_by_col.get(cur_col):
                                        row_data[field_by_col[cur_col]] = content
                                cur_col += 1
                            res.append(row_data)
                        else:
                            break
                    else:
                        break
                    cur_row += 1
            except Exception as e:
                raise UserError('Error on operation: %s' % str(e))
                    
        except Exception as e:
            raise UserError(str(e))
        return res

    @api.model
    def read_attachment(self, attachment, **kwargs):
        self.check_su()
        data = []
        if not attachment:
            raise UserError('Attachment Not Found')
        try:
            if attachment.mimetype in ('application/vnd.ms-excel', 'text/csv'):
                df = pandas.read_csv(BytesIO(attachment.raw), encoding="latin1")
            elif attachment.mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
                df = pandas.read_excel(BytesIO(attachment.raw))
            else:
                df = pandas.read_csv(BytesIO(attachment.raw), encoding="latin1")
            data = df.to_dict('records')
        except Exception as e:
            raise UserError(str(e))
        return data

    @api.model
    def read_attachment_by_name(self, attachment_name, **kwargs):
        self.check_su()
        Attachment = self.env['ir.attachment']
        attachment = Attachment.search([('name', '=', attachment_name)], limit=1)
        data = []
        if not attachment_name:
            raise UserError('Attachment Name Not Found')
        try:
            if attachment.mimetype in ('application/vnd.ms-excel', 'text/csv'):
                if pathlib.Path(attachment.name).suffix == '.xls':
                    df = pandas.read_excel(BytesIO(attachment.raw))
                else:
                    df = pandas.read_csv(BytesIO(attachment.raw), encoding="latin1")
            elif attachment.mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
                df = pandas.read_excel(BytesIO(attachment.raw))
            else:
                df = pandas.read_csv(BytesIO(attachment.raw), encoding="latin1")
            data = df.to_dict('records')
        except Exception as e:
            raise UserError(str(e))
        return data
    
    @api.model
    def read_attachment_df(self, attachment, **kwargs):
        self.check_su()
        df = False
        if not attachment:
            raise UserError('Attachment Not Found')
        try:
            if attachment.mimetype in ('application/vnd.ms-excel', 'text/csv'):
                df = pandas.read_csv(BytesIO(attachment.raw), encoding="latin1", **kwargs)
            elif attachment.mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
                df = pandas.read_excel(BytesIO(attachment.raw), **kwargs)
            else:
                df = pandas.read_csv(BytesIO(attachment.raw), encoding="latin1", **kwargs)
        except Exception as e:
            raise UserError(str(e))
        return df

    @api.model
    def gsheet_error_message(self, error):
        self.check_su()
        message = 'Something wrong from your google spreadsheet.\n\nError Details:\n'
        if isinstance(error, str):
            message += error
        else:
            error_exception = type(error).__name__
            if error_exception == 'APIError':
                response = json.loads(error.response.text)
                error_response = response.get('error')
                if error_response:
                    message += '%s' % error_response.get('message')
                else:
                    message += error.__doc__
            else:
                message += error.__doc__
        raise UserError(message)
    
    @api.model
    def gsheet_credential_handler(self, gsheet_credential):
        self.check_su()
        attachment = self.env['ir.attachment'].search([('name', '=', gsheet_credential)])
        if attachment.mimetype != 'application/json':
            self.gsheet_error_message('The credential must be json file.')
        credential = dict(pandas.read_json(BytesIO(attachment.raw), typ='series'))
        return credential
    
    @api.model
    def get_authorized_gsheet(self, gsheet_id, gsheet_credential):
        self.check_su()
        spreadsheet = False
        try:
            # Load credentials from the dictionary
            credential_dict = self.gsheet_credential_handler(gsheet_credential)
            credentials = ServiceAccountCredentials.from_json_keyfile_dict(credential_dict)
            # Authorize with gspread
            gc = gspread.authorize(credentials)

            #open the google spreadsheet
            spreadsheet = gc.open_by_key(gsheet_id)
        except Exception as e:
            self.gsheet_error_message(e)
        return spreadsheet
    
    @api.model
    def get_unauthorized_gsheet(self, gsheet_id, gsheet_name):
        self.check_su()
        data = []
        try:
            gsheet_url = "https://docs.google.com/spreadsheets/d/{}/gviz/tq?tqx=out:csv&sheet={}".format(
                gsheet_id, gsheet_name.replace(' ', '%20'))
            df = pandas.read_csv(gsheet_url)
            data = df.to_dict('records')
        except Exception as e:
            self.gsheet_error_message(e)
        return data

    @api.model
    def read_google_spreadsheet(self, gsheet_id='', gsheet_name='', gsheet_credential=''):
        self.check_su()
        data = []
        if not gsheet_credential:
            # Get data from unauthorized google spreadsheet
            data = self.get_unauthorized_gsheet(gsheet_id, gsheet_name)
        else:
            # Get data from authorized google spreadsheet
            spreadsheet = self.get_authorized_gsheet(gsheet_id, gsheet_credential)
            try:
                worksheet = spreadsheet.worksheet(gsheet_name) if gsheet_name else spreadsheet.get_worksheet(0)
                data = worksheet.get_all_records()
            except Exception as e:
                self.gsheet_error_message(e)
        return data

    @api.model
    def write_google_spreadsheet(self, gsheet_id='', gsheet_name='', gsheet_credential='', data=[]):
        self.check_su()
        # Get authorized Google Spreadsheet
        spreadsheet = self.get_authorized_gsheet(gsheet_id, gsheet_credential)

        try:
            worksheet = spreadsheet.worksheet(gsheet_name) if gsheet_name else spreadsheet.get_worksheet(0)

            # Write DataFrame to Google Spreadsheet
            df = pandas.DataFrame(data)
            header = df.columns.values.tolist()
            values = df.values.tolist()

            # Clear existing content in the worksheet
            worksheet.clear()

            # Update the worksheet with header and values using named arguments
            worksheet.update([header] + values)
        except Exception as e:
            self.gsheet_error_message(e)
        
    @api.model
    def insert_google_spreadsheet(self, izi_table=False, gsheet_id='', gsheet_name='', gsheet_credential=''):
        self.check_su()
        credential = self.gsheet_credential_handler(gsheet_credential)
        raw_data = self.read_google_spreadsheet(gsheet_id, gsheet_name, credential)

        if raw_data:
            # Convert keys to lowercase and replace spaces with underscores
            data = [{key.lower().replace(' ', '_'): value for key, value in datas.items()} for datas in raw_data]

            # Build Table Schma
            init_table = data[0]
            izi_table.get_table_fields_from_dictionary(init_table)
            izi_table.update_schema_store_table()
            
            # Truncate
            self.query_execute('TRUNCATE %s;' % izi_table.store_table_name)

            # Insert Data
            for r in data:
                self.query_insert('%s' % izi_table.store_table_name, r)
