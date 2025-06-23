from odoo import models, fields, api, _
from odoo.exceptions import UserError
import json
import requests
from datetime import date, datetime, timedelta
import string
import random
def token_generator(size=32, chars=string.ascii_lowercase + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))

file_code = '''
table = izi_table.search([('table_name','=','%s')])
model = table.model_id.model
fields = table.model_id.field_id
model_data = env[model].search([])
res, sample = table.get_table_fields_data(fields,model_data)

izi_table.get_table_fields_from_dictionary(sample)
izi_table.update_schema_store_table()
for data in res:
    izi.query_insert('%s',data)
'''
class IZIDashboard(models.Model):
    _inherit = 'izi.dashboard'

    izi_lab_api_key = fields.Char('IZI Lab API Key', compute='_compute_izi_lab_api_key')
    izi_lab_url = fields.Char('IZI Lab URL', compute='_compute_izi_lab_api_key')
    base_url = fields.Char('Base URL', compute='_compute_izi_lab_api_key')
    izi_dashboard_access_token = fields.Char('IZI Dashboard Access Token', compute='_compute_izi_lab_api_key')

    def _compute_izi_lab_api_key(self):
        for rec in self:
            rec.izi_lab_api_key = self.env.user.company_id.izi_lab_api_key
            rec.izi_lab_url = self.env['ir.config_parameter'].sudo().get_param('izi_lab_url')
            rec.base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            rec.izi_dashboard_access_token = self.env['ir.config_parameter'].sudo().get_param('izi_dashboard.access_token')
    
    def action_get_lab_analysis_config(self, analysis_id, analysis_name):
        izi_lab_url = self.env['ir.config_parameter'].sudo().get_param('izi_lab_url')
        if not izi_lab_url:
            raise UserError(_('Please set IZI Lab URL in System Parameters.'))
        res = requests.post('''%s/lab/analysis/%s/config''' % (izi_lab_url, analysis_id), json={
            'name': analysis_name,
            'izi_lab_api_key': self.env.company.izi_lab_api_key,
        })
        res = res.json()
        if res.get('result') and res.get('result').get('config'):
            data = res.get('result').get('config')
            # Call izi.dashboard.config.wizard to create dashboard
            if type(data) == dict:
                if data['method'] == 'table':
                    izi_table = self.create_mart_table(data)
                    # izi_table.method_direct_trigger()
                    res = {
                        'message':f'Mart table "{data["table_name"]}" created.',
                        'status': 200,
                        'success': True,
                    }
                    return res
            res = self.env['izi.dashboard.config.wizard'].create({
                'dashboard_id': self.id,
            }).process_wizard(data=data)
            if res.get('errors'):
                res = {
                    'message': res['errors'][0]['error'],
                    'status': 500,
                }
        else:
            res = res.get('result')
        return res
    
    def create_mart_table(self,data):
        izi_table_obj = self.env['izi.table']
        izi_table = izi_table_obj.create({
            'name': data['table_name'],
            'source_id': 1,
            'stored_option':'stored',
            'store_interval':'today',
            'is_stored': True,
            'is_direct': False,
        })
        izi_table.write({
            'main_code': data['main_code']
        })

        store_table_name = izi_table.store_table_name

        data['query'] = f'SELECT * FROM {store_table_name} LIMIT 100;'
        data['table_id'] = izi_table.id

        return izi_table

    @api.model
    def action_check_key(self):
        izi_lab_url = self.env['ir.config_parameter'].sudo().get_param('izi_lab_url')
        if not izi_lab_url:
            raise UserError(_('Please set IZI Lab URL in System Parameters.'))
        res = requests.post('''%s/lab/check''' % (izi_lab_url), json={
            'izi_lab_api_key': self.env.company.izi_lab_api_key,
        })
        res = res.json()
        res = res.get('result')
        return res

    def check_if_date_format(self, value):
        date_formats = ["%Y-%m-%d", "%Y-%m", "%Y"]
        res = False
        for date_format in date_formats:
            try:
                res = bool(datetime.strptime(value, date_format))
            except Exception as e:
                continue
        return res

    def check_if_datetime_format(self, value):
        datetime_format = "%Y-%m-%d %H:%M:%S"
        try:
            return bool(datetime.strptime(value, datetime_format))
        except Exception as e:
            return False

    def action_add_to_dashboard(self):
        result = {
            'status': 200,
            'analysis_id': False,
        }
        analysis = self.env['izi.analysis'].search([('name', '=', 'Analysis From AI')])
        if not analysis:
            analysis = self.env['izi.analysis'].search([('name', '=', 'Analysis From AI Table')])

        if analysis:
            new_analysis = analysis.with_context(action_copy=True, action_copy_from_conversation=True).copy()
            self.env['izi.dashboard.block'].create({
                'analysis_id': new_analysis.id,
                'dashboard_id': self.id,
            })
            result = {
                'status': 200,
                'analysis_id': new_analysis.id,
            }
        return result


    def action_execute_code(self, code, code_type):
        result = {
            'status': 200,
            'id': False,
        }
        try:
            # Unlink Default Analysis, Table
            analysis = self.env['izi.analysis'].search([('name', '=', 'Analysis From AI')])
            analysis.unlink()
            analysis = self.env['izi.analysis'].search([('name', '=', 'Analysis From AI Table')])
            analysis.unlink()
            table = self.env['izi.table'].search([('name', '=', 'Table From AI')])
            table.unlink()
            source = self.env['izi.data.source'].search([], limit=1)

            if code and code_type == 'sql':
                query = code
                # Check If Dashboard Has Table in AI Settings and Query Contain source_table_name
                # Replace source_table_name With The Table
                if self.table_id and 'source_table_name' in query:
                    if self.table_id.is_stored and self.table_id.store_table_name:
                        query = query.replace('source_table_name', self.table_id.store_table_name)
                    elif not self.table_id.is_stored and self.table_id.db_query:
                        query = query.replace('source_table_name', '(%s) source_table_name' % self.table_id.db_query)

                query_value = {}
                query = query.replace(';', '')
                if 'LIMIT' in query:
                    query_result = self.env['izi.tools'].sudo().query_fetch(query + ' ;')
                    if query_result:
                        query_value = query_result[0]
                else:
                    query_result = self.env['izi.tools'].sudo().query_fetch(query + ' LIMIT 1 ;')
                    if query_result:
                        query_value = query_result[0]
                
                # Create Table
                table = self.env['izi.table'].create({
                    'name': 'Table From AI',
                    'source_id': source.id,
                    'is_query': True,
                    'db_query': query,
                })
                table.get_table_fields()

                # Create Analysis
                analysis = self.env['izi.analysis'].create({
                    'name': 'Analysis From AI',
                    'method': 'query',
                    'table_id': table.id,
                })

                # Parse The Query
                dimension_fields_from_parsing = []
                tmp = ''
                if 'GROUP BY' in query and 'ORDER BY' in query:
                    tmp = query.split('GROUP BY')[1]
                    tmp = tmp.split('ORDER BY')[0]
                    tmp = tmp.split(',')
                    for t in tmp:
                        t = t.strip().replace('\n', '')
                        if t:
                            dimension_fields_from_parsing.append(t)
                guessed_overall_date_format = self._guess_date_format_in_key(query)
                # Check Key in Query Value
                metric_fields = []
                dimension_fields = []
                date_fields = []
                metric_field_ids = []
                dimension_field_ids = []
                date_field_ids = []
                date_format_by_field_id = {}
                for key in query_value:
                    value = query_value[key]
                    type_origin = 'varchar'
                    if type(value) == bool and not isinstance(value, int):
                        type_origin = 'boolean'
                        field = self.env['izi.table.field'].search([('field_name', '=', key), ('table_id', '=', table.id)], limit=1)
                        if field:
                            dimension_field_ids.append(field.id)
                            dimension_fields.append(key)
                    elif self.check_if_datetime_format(value) or isinstance(value, datetime):
                        type_origin = 'timestamp'
                        field = self.env['izi.table.field'].search([('field_name', '=', key), ('table_id', '=', table.id)], limit=1)
                        if field:
                            date_field_ids.append(field.id)
                            date_fields.append(key)
                            date_format = self._guess_date_format_in_key(key)
                            date_format_by_field_id[field.id] = date_format
                    elif self.check_if_date_format(value) or isinstance(value, date):
                        type_origin = 'date'
                        field = self.env['izi.table.field'].search([('field_name', '=', key), ('table_id', '=', table.id)], limit=1)
                        if field:
                            date_field_ids.append(field.id)
                            date_fields.append(key)
                            date_format = self._guess_date_format_in_key(key)
                            date_format_by_field_id[field.id] = date_format
                    elif isinstance(value, int) and not self._check_date_field_in_key(key) and (key not in dimension_fields_from_parsing): 
                        type_origin = 'int4'
                        field = self.env['izi.table.field'].search([('field_name', '=', key), ('table_id', '=', table.id)], limit=1)
                        if key == 'sum':
                            field.name = 'value_' + str(len(metric_fields) + 1)
                        if field:
                            metric_field_ids.append(field.id)
                            metric_fields.append(key)
                    elif isinstance(value, float) and not self._check_date_field_in_key(key) and (key not in dimension_fields_from_parsing):
                        type_origin = 'float8'
                        field = self.env['izi.table.field'].search([('field_name', '=', key), ('table_id', '=', table.id)], limit=1)
                        if key == 'sum':
                            field.name = 'value_' + str(len(metric_fields) + 1)
                        if field:
                            metric_field_ids.append(field.id)
                            metric_fields.append(key)
                    elif self._guess_date_format_in_key(key) and (key in dimension_fields_from_parsing):
                        field = self.env['izi.table.field'].search([('field_name', '=', key), ('table_id', '=', table.id)], limit=1)
                        if field:
                            date_field_ids.append(field.id)
                            date_fields.append(key)
                            date_format = self._guess_date_format_in_key(key)
                            date_format_by_field_id[field.id] = date_format
                    else:
                        field = self.env['izi.table.field'].search([('field_name', '=', key), ('table_id', '=', table.id)], limit=1)
                        if field:
                            dimension_field_ids.append(field.id)
                            dimension_fields.append(key)
                
                # Visual Type
                visual_type_name = 'scrcard_basic'
                if len(metric_fields) and len(date_fields):
                    visual_type_name = 'line'
                    analysis.limit = 365
                elif len(metric_fields) and len(dimension_fields):
                    visual_type_name = 'bar'
                    analysis.limit = 20
                if len(metric_fields) == 2 and len(date_fields) == 0:
                    visual_type_name = 'scatter'
                    analysis.limit = 50
                visual_type = self.env['izi.visual.type'].search([('name', '=', visual_type_name)], limit=1)
                analysis.visual_type_id = visual_type.id

                # Metric & Dimension
                date_field_ids = self._sort_date_field_ids(date_field_ids, date_format_by_field_id)
                for field_id in date_field_ids:
                    dimension = self.env['izi.analysis.dimension'].create({
                        'field_id': field_id,
                        'field_format': date_format_by_field_id.get(field_id),
                        'analysis_id': analysis.id,
                    })
                for field_id in dimension_field_ids:
                    dimension = self.env['izi.analysis.dimension'].create({
                        'field_id': field_id,
                        'analysis_id': analysis.id,
                    })
                analysis.metric_ids.unlink()
                for field_id in metric_field_ids:
                    metric = self.env['izi.analysis.metric'].create({
                        'field_id': field_id,
                        'calculation': 'sum',
                        'analysis_id': analysis.id,
                    })
                for field_id in date_field_ids:
                    sort = self.env['izi.analysis.sort'].create({
                        'field_id': field_id,
                        'sort': 'asc',
                        'analysis_id': analysis.id,
                    })
                for field_id in metric_field_ids:
                    sort = self.env['izi.analysis.sort'].create({
                        'field_id': field_id,
                        'sort': 'desc',
                        'analysis_id': analysis.id,
                    })
                result['id'] = analysis.id
            elif code and code_type == False:
                line_params = code
                analysis_method = 'table'
                if self.table_id.is_stored:
                    analysis_method = 'table'
                elif self.table_id.db_query:
                    analysis_method = 'query'
                elif self.table_id.model_id:
                    analysis_method = 'model'
                analysis = self.env['izi.analysis'].create({
                    'name': 'Analysis From AI',
                    'method': analysis_method,
                    'table_id':  self.table_id.id,
                })
                vals = analysis.prepare_analysis_from_line_parameters(line_params)
                analysis.write(vals)
                # Generate Visual Type
                date_fields = []
                for dimension in analysis.dimension_ids:
                    if dimension.field_id.field_type in ('date', 'datetime'):
                        date_fields.append(dimension.field_id)
                visual_type_name = 'scrcard_basic'
                if len(analysis.metric_ids) and len(date_fields):
                    visual_type_name = 'line'
                    # analysis.limit = 365
                elif len(analysis.metric_ids) and len(analysis.dimension_ids):
                    visual_type_name = 'bar'
                    analysis.limit = 20
                if len(analysis.metric_ids) == 2 and len(date_fields) == 0:
                    visual_type_name = 'scatter'
                    analysis.limit = 50
                visual_type = self.env['izi.visual.type'].search([('name', '=', visual_type_name)], limit=1)
                analysis.visual_type_id = visual_type.id
                result['id'] = analysis.id

        except Exception as e:
            result = {
                'status': 500,
                'error': str(e),
                'id': False,
            }
        return result
    
    def action_execute_config(self, analysis_config, table_name = False):
        result = {
            'status': 200,
            'id': False,
        }
        try:
            # Unlink Default Analysis, Table
            analysis = self.env['izi.analysis'].search([('name', '=', 'Analysis From AI')])
            analysis.unlink()
            analysis = self.env['izi.analysis'].search([('name', '=', 'Analysis From AI Table')])
            analysis.unlink()
            table = self.env['izi.table'].search([('name', '=', 'Table From AI')])
            table.unlink()
            source = self.env['izi.data.source'].search([], limit=1)
            if analysis_config:
                if analysis_config.get('query'):
                    query = analysis_config.get('query')
                    if self.table_id and 'source_table_name' in query:
                        if self.table_id.is_stored and self.table_id.store_table_name:
                            query = query.replace('source_table_name', self.table_id.store_table_name)
                        elif not self.table_id.is_stored and self.table_id.db_query:
                            query = query.replace('source_table_name', '(%s) source_table_name' % self.table_id.db_query)
                    
                    # Create Table
                    table = self.env['izi.table'].create({
                        'name': 'Table From AI',
                        'source_id': source.id,
                        'is_query': True,
                        'db_query': query,
                    })
                    table.get_table_fields()
                    if analysis_config.get('query') and not analysis_config.get('metrics'):
                        return {
                            'status': 500,
                            'error': "The Query Is Ok. But The Metrics / Dimensions Have To Be Defined Also!",
                            'id': False,
                        }

                    # Create Analysis
                    analysis = self.env['izi.analysis'].create({
                        'name': 'Analysis From AI',
                        'method': 'query',
                        'table_id': table.id,
                    })
                else:
                    if not table_name:
                        analysis_method = 'table'
                        if self.table_id.is_stored:
                            analysis_method = 'table'
                        elif self.table_id.db_query:
                            analysis_method = 'query'
                        elif self.table_id.model_id:
                            analysis_method = 'model'
                        analysis = self.env['izi.analysis'].create({
                            'name': 'Analysis From AI',
                            'method': analysis_method,
                            'table_id':  self.table_id.id,
                            'model_id': self.table_id.model_id.id if self.table_id.model_id else False,
                        })
                    else:
                        izi_table_obj = self.env['izi.table']
                        search_code = f"table = izi_table.search([('table_name','=','{table_name}')])"
                        izi_table = izi_table_obj.search([('name','ilike','Mart Table From AI'),('main_code','ilike',search_code)])
                        if not izi_table:
                            izi_table = izi_table_obj.search([('name','ilike','Mart Table From AI')])
                            if izi_table:
                                count = len(izi_table)
                                name = f'Mart Table From AI {count + 1}'
                            else:
                                name = 'Mart Table From AI'

                            izi_table = izi_table_obj.create({
                                    'name': name,
                                    'source_id': 1,
                                    'stored_option':'stored',
                                    'store_interval':'today',
                                    'is_stored': True,
                                    'is_direct': False,
                                })
                        code = file_code % (str(table_name), izi_table.store_table_name)
                        izi_table.write({
                            'main_code': code
                        })
                        izi_table.method_direct_trigger()
                        analysis_method = 'table'
                        analysis = self.env['izi.analysis'].create({
                            'name': 'Analysis From AI Table',
                            'method': analysis_method,
                            'table_id':  izi_table.id,
                            'model_id': izi_table.model_id.id if izi_table.model_id else False,
                        })

                
                # Define Metric, Dimensions, Sorts
                vals = analysis.prepare_analysis_from_config(analysis_config)
                analysis.write(vals)
                
                # Define Visual Type
                date_fields = []
                date_fields_format = []
                for dimension in analysis.dimension_ids:
                    if dimension.field_id.field_type in ('date', 'datetime'):
                        date_fields.append(dimension.field_id)
                        date_fields_format.append(dimension.field_format)
                visual_type_name = 'table'
                if len(analysis.metric_ids) and len(date_fields):
                    visual_type_name = 'line'
                    analysis.limit = 365 * 2
                    if 'day' in date_fields_format:
                        analysis.limit = 365 * 2
                        if len(analysis.dimension_ids) >= 2:
                            analysis.limit = 365 * 2 * 10
                    elif 'week' in date_fields_format:
                        analysis.limit = 52 * 2
                        if len(analysis.dimension_ids) >= 2:
                            analysis.limit = 52 * 2 * 10
                    elif 'month' in date_fields_format:
                        analysis.limit = 12 * 2
                        if len(analysis.dimension_ids) >= 2:
                            analysis.limit = 12 * 2 * 10
                    elif 'year' in date_fields_format:
                        analysis.limit = 1 * 2
                        if len(analysis.dimension_ids) >= 2:
                            analysis.limit = 1 * 2 * 10
                elif len(analysis.metric_ids) == 2 and len(analysis.dimension_ids) == 0:
                    visual_type_name = 'scrcard_progress'
                    analysis.limit = 10
                elif len(analysis.metric_ids) == 2 and len(date_fields) == 0:
                    visual_type_name = 'bar_line'
                    analysis.limit = 50
                elif len(analysis.metric_ids) > 2 or len(analysis.dimension_ids) > 2:
                    visual_type_name = 'table'
                    analysis.limit = 100
                elif len(analysis.metric_ids) and len(analysis.dimension_ids):
                    visual_type_name = 'bar'
                    analysis.limit = 20
                visual_type = self.env['izi.visual.type'].search([('name', '=', visual_type_name)], limit=1)
                analysis.visual_type_id = visual_type.id
                result['id'] = analysis.id
        except Exception as e:
            result = {
                'status': 500,
                'error': str(e),
                'id': False,
            }
        return result
    
    def _check_date_field_in_key(self, key):
        res = False
        if (key in ('date', 'day', 'week', 'quarter', 'month', 'year', 'date_number', 'day_number', 'week_number', 'quarter_number', 'month_number', 'year_number')):
            res = True
        return res

    def _sort_date_field_ids(self, date_field_ids, date_format_by_field_id):
        result = []
        day_fields = []
        week_fields = []
        month_fields = []
        quarter_fields = []
        year_fields = []
        other_fields = []
        for df in date_field_ids:
            date_format = date_format_by_field_id[df]
            if date_format == 'day':
                day_fields.append(df)
            elif date_format == 'week':
                week_fields.append(df)
            elif date_format == 'month':
                month_fields.append(df)
            elif date_format == 'quarter':
                quarter_fields.append(df)
            elif date_format == 'year':
                year_fields.append(df)
            else:
                other_fields.append(df)
        result = day_fields + week_fields + month_fields + quarter_fields + year_fields + other_fields
        return result

    def _guess_date_format_in_key(self, key):
        if 'date' in key or 'day' in key or 'daily' in key:
            return 'day'
        if 'week' in key:
            return 'week'
        if 'month' in key:
            return 'month'
        if 'quarter' in key:
            return 'quarter'
        if 'year' in key or 'annual' in key:
            return 'year'
        return False

    def _format_new_message_content(self, new_message_content):
        code = ''
        code_type = False
        quick_messages = []
        if new_message_content:
            if '# START_CODE_SQL' in new_message_content and '# END_CODE_SQL' in new_message_content:
                code = new_message_content
                code = code.split('# START_CODE_SQL')[1]
                code = code.split('# END_CODE_SQL')[0]
                code_type = 'sql'
            if '# START_CODE' in new_message_content and '# END_CODE' in new_message_content:
                code = new_message_content
                code = code.split('# START_CODE')[1]
                code = code.split('# END_CODE')[0]
            if '<div class="code_content code_content_sql">' in new_message_content:
                code = new_message_content
                code = code.split('<div class="code_content code_content_sql">')[1]
                if '<div class="code_execution">' in new_message_content:
                    code = code.split('<div class="code_execution">')[0]
                if '</div>' in new_message_content:
                    code = code.split('</div>')[0]
            if '# START_CODE' in new_message_content and '# END_CODE' in new_message_content:
                new_message_content = new_message_content.replace('# START_CODE_SQL\n', '<div class="code_content code_content_sql">')
                new_message_content = new_message_content.replace('# START_CODE_SQL', '<div class="code_content code_content_sql">')
                new_message_content = new_message_content.replace('# START_CODE_PYTHON\n', '<div class="code_content code_content_python">')
                new_message_content = new_message_content.replace('# START_CODE_PYTHON', '<div class="code_content code_content_python">')
                new_message_content = new_message_content.replace('# START_CODE\n', '<div class="code_content">')
                new_message_content = new_message_content.replace('# START_CODE', '<div class="code_content">')
                new_message_content = new_message_content.replace('# END_CODE_SQL', '<div class="code_execution"><span class="material-icons">play_arrow</span></div></div>')
                new_message_content = new_message_content.replace('# END_CODE_PYTHON', '</div>')
                new_message_content = new_message_content.replace('# END_CODE', '</div>')
            if '# START_SUMMARY' in new_message_content and '# END_SUMMARY' in new_message_content:
                quick_messages = new_message_content
                quick_messages = quick_messages.split('# START_SUMMARY')[1]
                quick_messages = quick_messages.split('# END_SUMMARY')[0]
                new_message_content = ''
                if quick_messages:
                    quick_messages = quick_messages.split('\n')
                    new_quick_messages = []
                    for q in quick_messages:
                        if q.strip():
                            new_quick_messages.append(q.replace('- ', '').strip())
                    quick_messages = new_quick_messages
                    new_message_content = new_quick_messages
                    new_message_content = '\n'.join(new_quick_messages)
        return new_message_content, code, code_type, quick_messages

    def action_get_lab_ask(self, messages, retry_count=0):
        result = {
            'status': 200,
            'raw_messages': [],
            'new_messages': [],
        }
        izi_lab_url = self.env['ir.config_parameter'].sudo().get_param('izi_lab_url')
        table_information = ''
        table_name = ''
        table_prompt = ''
        if self.table_id:
            table_name = self.table_id.table_name
            table_information += ('field_name;field_type;description;\n')
            for field in self.table_id.field_ids:
                table_information += ('%s;%s;%s;\n' % (field.field_name, field.field_type, field.description or ''))
            if self.table_id.ai_prompt:
                table_prompt = self.table_id.ai_prompt
        else:
            # raise UserError(_('Please Set The Table First For AI Assistance.'))
            return  {
                'status': 500,
                'message': _('Please Set The Table First For AI Assistance.'),
            }
        if not izi_lab_url:
            # raise UserError(_('Please Set IZI Lab URL in System Parameters.'))
            return  {
                'status': 500,
                'message': _('Please Set IZI Lab URL in System Parameters.'),
            }
        if retry_count > 3:
            if messages and messages[-1].get('role') == 'system':
                return  {
                    'status': 500,
                    'message': messages[-1].get('content'),
                }
            return  {
                'status': 500,
                'message': _('Maximum Retry Count.'),
            }
        if messages:
            result['raw_messages'] = messages.copy()
            question_from_last_message = messages[-1].get('content')
            try:
                res = requests.post('''%s/lab/analysis/ask''' % (izi_lab_url), json={
                    'izi_lab_api_key': self.env.company.izi_lab_api_key,
                    'messages': messages,
                    'table_information': table_information,
                    'table_prompt': table_prompt,
                    'language': self.lang_id.name if self.lang_id else 'English',
                }, timeout=120)
                res = res.json()
                if res.get('result') and res.get('result').get('status') == 200 and res.get('result').get('new_message_content'):
                    new_message_content = res.get('result').get('new_message_content')
                    # If Analysis Config
                    analysis_config = {}
                    if type(new_message_content) == dict:
                        analysis_config = new_message_content.copy()
                        new_message_content = '# START_CODE' + str(new_message_content) + '# END_CODE'
                    
                    new_raw_message = {
                        'role': 'assistant',
                        'content': str(res.get('result').get('new_message_content')),
                    }
                    new_message_content, code, code_type, quick_messages = self._format_new_message_content(new_message_content)
                    new_message = {
                        'role': 'assistant',
                        'content': str(new_message_content),
                    }
                    result['raw_messages'].append(new_raw_message)
                    result['new_messages'].append(new_message)
                    result['quick_messages'] = quick_messages
                    messages.append(new_message)
                    # Try Run Specific Code SQL
                    if analysis_config:
                        # Comment Out First For Future Development
                        # analysis_res = self.action_execute_config(analysis_config, table_name)
                        analysis_res = self.action_execute_config(analysis_config)
                        if (analysis_res and analysis_res['status'] == 200) :
                            analysis_id = analysis_res['id']
                            analysis_data = []
                            if analysis_id:
                                analysis = self.env['izi.analysis'].browse(analysis_id)
                                if analysis:
                                    kwargs = {}
                                    if analysis_config.get('filters') and not analysis_config.get('query'):
                                        # If There Is Query, Do Not Filter Again
                                        kwargs['filters'] = {}
                                        kwargs['filters']['action'] = analysis_config.get('filters')
                                    analysis_data = analysis.get_analysis_data_dashboard(**kwargs)
                                    analysis_data = analysis_data['data']
                            if analysis_data:
                                res_after_data = requests.post('''%s/lab/analysis/ask/explain''' % (izi_lab_url), json={
                                    'izi_lab_api_key': self.env.company.izi_lab_api_key,
                                    'question': question_from_last_message,
                                    'data': str(analysis_data),
                                    'language': self.lang_id.name if self.lang_id else 'English',
                                }, timeout=120)
                                res_after_data = res_after_data.json()
                                if res_after_data.get('result') and res_after_data.get('result').get('status') == 200 and res_after_data.get('result').get('new_message_content'):
                                    new_message_content = res_after_data.get('result').get('new_message_content')
                                    new_raw_message = {
                                        'role': 'assistant',
                                        'content': str(res_after_data.get('result').get('new_message_content')).replace('*', ''),
                                    }
                                    result['analysis_id'] = analysis_id
                                    result['analysis_config'] = analysis_config
                                    new_message = {
                                        'role': 'assistant',
                                        'content': str(new_message_content).replace('*', ''),
                                    }
                                    result['raw_messages'].append(new_raw_message)
                                    result['new_messages'].append(new_message)
                                else:
                                    return {
                                        'status': 500,
                                        'message': res_after_data.get('result').get('message') or '',
                                    }
                        else:
                            if analysis_res.get('error'):
                                retry_messages = messages.copy()
                                retry_messages.append({
                                    'role': 'system',
                                    'content': str(analysis_res['error']),
                                })
                                return self.action_get_lab_ask(retry_messages, retry_count=retry_count+1)
                                return {
                                    'status': 500,
                                    'message': str(analysis_config) + '\n' + str(analysis_res['error']),
                                }
                        
                elif res.get('result') and res.get('result').get('status') and res.get('result').get('status') != 200:
                    result = {
                        'status': res.get('result').get('status'),
                        'message': res.get('result').get('message') or '',
                    }
            except Exception as e:
                result = {
                    'status': 500,
                    'message': str(e),
                }
        return result
    
    def generate_access_token(self, context, expiration_hour=False):
        if expiration_hour:
            token_expired_hours = expiration_hour
        else:
            token_expired_hours = self.env['ir.config_parameter'].sudo().get_param('izi_dashboard.token_expired_hours')
            if not token_expired_hours:
                token_expired_hours = 1
        token = self.env['izi.dashboard.token'].sudo().create({
            'name': 'Dashboard Access Token',
            'token': token_generator(),
            'is_active': True,
            'dashboard_id': int(self.id),
            'expired_date': fields.Datetime.now() + timedelta(hours=int(token_expired_hours)),
            'context':context,
            'user_id':self.env.user.id

        })
        return token.token
    
class IZIDashboardToken(models.Model):
    _name = 'izi.dashboard.token'
    _description = 'IZI Dashboard Token'

    name = fields.Char('Name')
    token = fields.Char('Token')
    dashboard_id = fields.Many2one('izi.dashboard', 'Dashboard')
    user_id = fields.Many2one('res.users', 'User')
    is_active = fields.Boolean('Active', default=True)
    expired_date = fields.Datetime('Expired Date')
    context = fields.Char('context')