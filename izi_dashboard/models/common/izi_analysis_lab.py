from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import json

class IZIAnalysis(models.Model):
    _inherit = 'izi.analysis'

    ai_analysis_text = fields.Text('AI Analysis Text', default='There is no description yet.')
    ai_explore_analysis_ids = fields.One2many('izi.analysis', 'parent_analysis_id', string='AI Explore Analysis')
    parent_analysis_id = fields.Many2one('izi.analysis', string='Parent Analysis')
    ai_language = fields.Char('AI Language')

    @api.model_create_multi
    def create(self, vals_list):
        recs = super(IZIAnalysis, self).create(vals_list)
        if self._context.get('copy'):
            return recs
        for rec in recs:
            if self._context.get('ai_create'):
                try:
                    izi_lab_url = self.env['ir.config_parameter'].sudo().get_param('izi_lab_url')
                    if not izi_lab_url:
                        raise UserError(_('Please set IZI Lab URL in System Parameters.'))
                    
                    # Get Metric and Dimension Information
                    fields = rec.table_id.field_ids
                    metrics = []
                    dimensions = []
                    for field in fields:
                        if field.field_type in ('numeric', 'number'):
                            metrics.append(field.field_name)
                        else:
                            dimensions.append(field.field_name)
                    res = requests.post('''%s/lab/analysis/create''' % (izi_lab_url), json={
                        'izi_lab_api_key': self.env.company.izi_lab_api_key,
                        'data': {
                            'title': rec.name,
                            'metrics': metrics,
                            'dimensions': dimensions,
                        },
                    }, timeout=120)
                    res = res.json()
                    if res.get('result') and res.get('result').get('status') == 200 and res.get('result').get('result'):
                        result = res.get('result').get('result')
                        analysis_vals = rec.prepare_analysis_from_line_parameters(result)
                        rec.write(analysis_vals)
                except Exception as e:
                    pass
        return recs

    def prepare_analysis_from_line_parameters(self, line_params):
        # Define Fields
        rec = self
        fields = rec.table_id.field_ids
        metric_by_name = {}
        dimension_by_name = {}
        date_dimension_by_name = {}
        other_dimension_by_name = {}
        field_by_name = {}
        for field in fields:
            if field.field_type in ('numeric', 'number'):
                metric_by_name[field.field_name] = field.id
            else:
                dimension_by_name[field.field_name] = field.id
                if field.field_type in ('date', 'datetime'):
                    date_dimension_by_name[field.field_name] = field.id
                else:
                    other_dimension_by_name[field.field_name] = field.id
            field_by_name[field.field_name] = field.id
        
        # Process Line Params
        line_params = line_params.split('\n')
        vals = {}
        new_metric_vals = []
        new_dimension_vals = []
        new_sort_vals = []
        for row in line_params:
            row = row.strip()
            row = row.split('=')
            if len(row) == 2 and row[0] == 'metric':
                m = row[1]
                m = m.split(':')
                calculation = 'sum'
                if len(m) == 2:
                    calculation = m[1]
                m = m[0]
                if m in metric_by_name:
                    metric_id = metric_by_name[m]
                    new_metric_vals.append((0, 0, {
                        'field_id': metric_id,
                        'calculation': calculation,
                    }))
            
            if len(row) == 2 and row[0] == 'dimension':
                d = row[1]
                d = d.split(':')
                field_format = False
                if len(d) == 2:
                    field_format = d[1]
                d = d[0]
                if d in dimension_by_name:
                    dimension_id = dimension_by_name[d]
                    new_dimension_vals.append((0, 0, {
                        'field_id': dimension_id,
                        'field_format': field_format,
                    }))

            if len(row) == 2 and row[0] == 'sort':
                s = row[1]
                s = s.split(':')
                sort = 'asc'
                if len(s) == 2:
                    sort = s[1]
                s = s[0]
                if s in field_by_name:
                    field_id = field_by_name[s]
                    new_sort_vals.append((0, 0, {
                        'field_id': field_id,
                        'sort': sort,
                    }))
            
            if len(row) == 2 and row[0] == 'visual_type':
                visual_type_name = row[1]
                if visual_type_name == 'scorecard':
                    visual_type_name = 'scrcard_basic'
                visual_type = self.env['izi.visual.type'].search([('name', '=', visual_type_name)], limit=1)
                if visual_type:
                    vals['visual_type_id'] = visual_type.id
            
            if len(row) == 2 and row[0] == 'limit':
                limit = row[1]
                vals['limit'] = int(limit)
            
        rec.metric_ids.unlink()
        rec.dimension_ids.unlink()
        rec.sort_ids.unlink()
        vals['metric_ids'] = new_metric_vals
        vals['dimension_ids'] = new_dimension_vals
        vals['sort_ids'] = new_sort_vals
        return vals

    def prepare_analysis_from_config(self, config):
        # Define Fields
        rec = self
        fields = rec.table_id.field_ids
        metric_by_name = {}
        dimension_by_name = {}
        date_dimension_by_name = {}
        other_dimension_by_name = {}
        field_by_name = {}
        operator_by_name = {}
        operators = self.env['izi.analysis.filter.operator'].search([])
        for field in fields:
            if field.field_type in ('numeric', 'number'):
                metric_by_name[field.field_name] = field.id
            dimension_by_name[field.field_name] = field.id
            if field.field_type in ('date', 'datetime'):
                date_dimension_by_name[field.field_name] = field.id
            else:
                other_dimension_by_name[field.field_name] = field.id
            field_by_name[field.field_name] = field.id
        for op in operators:
            operator_by_name[op.name] = op.id
        
        # Process Config
        vals = {}
        new_metric_vals = []
        new_dimension_vals = []
        new_sort_vals = []
        new_filter_vals = []
        
        for metric in config.get('metrics', []):
            m = metric.get('field_name') or metric.get('field')
            calculation = metric.get('calculation')
            if m in metric_by_name:
                metric_id = metric_by_name[m]
                new_metric_vals.append((0, 0, {
                    'field_id': metric_id,
                    'calculation': calculation,
                }))
        
        for dimension in config.get('dimensions', []):
            d = dimension.get('field_name') or dimension.get('field')
            field_format = dimension.get('field_format') or dimension.get('format')
            if d in dimension_by_name:
                dimension_id = dimension_by_name[d]
                if field_format and field_format not in ['day', 'week', 'month', 'quarter', 'year']:
                    field_format = False
                new_dimension_vals.append((0, 0, {
                    'field_id': dimension_id,
                    'field_format': field_format,
                }))
        
        # Deprecated
        # for dimension in config.get('dimensions', []):
        #     d = dimension.get('field_name')
        #     field_format = dimension.get('field_format')
        #     if d in date_dimension_by_name:
        #         dimension_id = dimension_by_name[d]
        #         new_dimension_vals.append((0, 0, {
        #             'field_id': dimension_id,
        #             'field_format': field_format,
        #         }))
        # for dimension in config.get('dimensions', []):
        #     d = dimension.get('field_name')
        #     field_format = dimension.get('field_format')
        #     if d in other_dimension_by_name:
        #         dimension_id = dimension_by_name[d]
        #         new_dimension_vals.append((0, 0, {
        #             'field_id': dimension_id,
        #         }))
        
        for sort in config.get('sorts', []):
            s = sort.get('field_name') or sort.get('field')
            sort = sort.get('sort')
            if s in field_by_name:
                field_id = field_by_name[s]
                new_sort_vals.append((0, 0, {
                    'field_id': field_id,
                    'sort': sort,
                }))

        for filter in config.get('filters', []):
            f = filter.get('field_name') or filter.get('field')
            op = filter.get('operator')
            value = filter.get('value')
            if f in field_by_name and op in operator_by_name:
                field_id = field_by_name[f]
                op_id = operator_by_name[op]
                if op.lower() in ('in', 'not in'):
                    if type(value) in (list, tuple):
                        value_str = []
                        for val in value:
                            if type(val) in (int, float):
                                value_str.append(str(val))
                            else:
                                value_str.append('$$%s$$' % val)
                        value_str = (',').join(value_str)
                        value = '(%s)' % value_str
                elif type(value) not in (int, float):
                    value = '$$%s$$' % value
                new_filter_vals.append((0, 0, {
                    'condition': 'and',
                    'field_id': field_id,
                    'operator_id': op_id,
                    'value': value,
                }))
        
        vals['limit'] = int(config.get('limit', 10))
        rec.metric_ids.unlink()
        rec.dimension_ids.unlink()
        rec.sort_ids.unlink()
        vals['metric_ids'] = new_metric_vals
        vals['dimension_ids'] = new_dimension_vals
        vals['sort_ids'] = new_sort_vals
        vals['filter_ids'] = new_filter_vals
        return vals

    def start_lab_analysis_explore(self):
        result = {
            'status': 200,
            'analysis_explore_ids': [],
        }
        res_explore_values = []
        izi_lab_url = self.env['ir.config_parameter'].sudo().get_param('izi_lab_url')
        if not izi_lab_url:
            raise UserError(_('Please set IZI Lab URL in System Parameters.'))
        ai_explore_data = {
            'table_name': self.table_id.name,
            'fields': [],
        }
        for field in self.table_id.field_ids:
            ai_explore_data['fields'].append({
                'field_name': field.field_name,
                'field_type': field.field_type,
            })
        try:
            res = requests.post('''%s/lab/analysis/explore''' % (izi_lab_url), json={
                'izi_lab_api_key': self.env.company.izi_lab_api_key,
                'data': ai_explore_data,
            }, timeout=120)
            res = res.json()
            if res.get('result') and res.get('result').get('status') == 200 and res.get('result').get('explore'):
                res_explore_values = res.get('result').get('explore')
            elif res.get('result') and res.get('result').get('status') and res.get('result').get('status') != 200:
                return {
                    'status': res.get('result').get('status'),
                    'message': res.get('result').get('message') or '',
                }
        except Exception as e:
            pass
        
        if not res_explore_values:
            res_explore_values = []
        analysis_explores = []
        existing_analysis_explore = self.env['izi.analysis'].search(['|', ('active', '=', False), ('active', '=', True), ('parent_analysis_id', '=', self.id)])
        existing_analysis_explore.unlink()
        index = 0
        for val in res_explore_values:
            metric_values = []
            sort_values = []
            if val.get('metrics'):
                for metric in val.get('metrics'):
                    metric_field_name = metric.get('field_name')
                    metric_calculation = metric.get('calculation')
                    metric_field = self.env['izi.table.field'].search([('table_id', '=', self.table_id.id), ('field_name', '=', metric_field_name)], limit=1)
                    if metric_field:
                        metric_values.append((0, 0, {
                            'field_id': metric_field.id,
                            'calculation': metric_calculation,
                        }))
                        sort_values.append((0, 0, {
                            'field_id': metric_field.id,
                            'sort': 'desc',
                        }))
            dimension_values = []
            if val.get('dimensions'):
                for dimension in val.get('dimensions'):
                    dimension_field_name = dimension.get('field_name')
                    dimension_field_format = dimension.get('field_format')
                    dimension_field = self.env['izi.table.field'].search([('table_id', '=', self.table_id.id), ('field_name', '=', dimension_field_name)], limit=1)
                    if dimension_field:
                        dimension_values.append((0, 0, {
                            'field_id': dimension_field.id,
                            'field_format': dimension_field_format,
                        }))
            visual_type_name = val.get('visual_type')
            visual_type = self.env['izi.visual.type'].search([('name', '=', visual_type_name)], limit=1)
            if metric_values and visual_type:
                index += 1
                new_analysis = self.copy({
                    'name': val.get('name'),
                    'metric_ids': metric_values,
                    'dimension_ids': dimension_values,
                    'sort_ids': sort_values,
                    'visual_type_id': visual_type.id,
                    'parent_analysis_id': self.id,
                    'limit': 5,
                    'active': False,
                })
                for vc in new_analysis.analysis_visual_config_ids:
                    if vc.visual_config_id.name == 'legendPosition':
                        vc.write({
                            'string_value': 'none',
                        })
                    if vc.visual_config_id.name == 'rotateLabel':
                        vc.write({
                            'string_value': 'true',
                        })
                analysis_explores.append({
                    'id': new_analysis.id,
                    'name': new_analysis.name,
                })
        return {
            'status': 200,
            'analysis_explores': analysis_explores,
        }
    
    def save_lab_analysis_explore(self, dashboard_id):
        for analysis in self:
            analysis.write({
                'active': True,
                'limit': 50,
                'parent_analysis_id': False,
            })
            for vc in analysis.analysis_visual_config_ids:
                if vc.visual_config_id.name == 'legendPosition':
                    vc.write({
                        'string_value': 'right',
                    })
            if dashboard_id:
                self.env['izi.dashboard.block'].create({
                    'dashboard_id': dashboard_id,
                    'analysis_id': analysis.id,
                })
        return True

    def action_get_lab_description(self, ai_analysis_data, block_id = False, dashboard_id = False):
        result = {
            'status': 200,
            'ai_analysis_text': self.ai_analysis_text,
        }
        izi_lab_url = self.env['ir.config_parameter'].sudo().get_param('izi_lab_url')
        if not izi_lab_url:
            raise UserError(_('Please set IZI Lab URL in System Parameters.'))
        analysis_name = self.name
        visual_type_name = self.visual_type_id.name
        if not dashboard_id:
            language = self.env['izi.dashboard.block'].browse(block_id).dashboard_id.lang_id.name
        else:
            language = self.env['izi.dashboard'].browse(dashboard_id).lang_id.name

        # if self.ai_analysis_text == 'There is no description yet.' or self.ai_language != language:
        if True:
            try:
                self.ai_language = language
                res = requests.post('''%s/lab/analysis/description''' % (izi_lab_url), json={
                    'izi_lab_api_key': self.env.company.izi_lab_api_key,
                    'analysis_name': analysis_name,
                    'visual_type_name': visual_type_name,
                    'language': self.ai_language,
                    'data': ai_analysis_data,
                    'is_short': self._context.get('is_short', False),
                }, timeout=120)
                res = res.json()
                if res.get('result') and res.get('result').get('status') == 200 and res.get('result').get('description'):
                    description = res.get('result').get('description')
                    self.ai_analysis_text = description
                elif res.get('result') and res.get('result').get('status') and res.get('result').get('status') != 200:
                    result = {
                        'status': res.get('result').get('status'),
                        'message': res.get('result').get('message') or '',
                    }
            except Exception as e:
                pass
            result['ai_analysis_text'] = self.ai_analysis_text
        return result

    def action_get_lab_insight(self, ai_analysis_data, drilldown_level, drilldown_title, languange):
        result = {
            'status': 200,
            'insights': [],
            'drilldowns': [],
            'parent': [],
        }
        izi_lab_url = self.env['ir.config_parameter'].sudo().get_param('izi_lab_url')
        if not izi_lab_url:
            raise UserError(_('Please set IZI Lab URL in System Parameters.'))
        # izi_lab_url = "http://localhost:8014"
        analysis_name = self.name
        visual_type_name = self.visual_type_id.name
        try:
            res = requests.post('''%s/lab/analysis/insight''' % (izi_lab_url), json={
                'izi_lab_api_key': self.env.company.izi_lab_api_key,
                'analysis_name': analysis_name,
                'visual_type_name': visual_type_name,
                'language': False,
                'data': ai_analysis_data,
                'drilldown_level': drilldown_level,
                'drilldown_title': drilldown_title,
                'languange':languange,
            }, timeout=120)
            res = res.json()
            if res.get('result') and res.get('result').get('status') == 200 and res.get('result').get('result'):
                res_json = res.get('result').get('result')
                res_json = json.loads(res_json)
                result['insights'] = res_json.get('insights')
                result['parent'] = res.get('result').get('parent')
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
    
    def action_get_speech_text_ai(self, data):
        result = {
            'status': 200,
            'ai_speech_text': False,
        }
        izi_lab_url = self.env['ir.config_parameter'].sudo().get_param('izi_lab_url')
        if not izi_lab_url:
            raise UserError(_('Please set IZI Lab URL in System Parameters.'))
        try:
            res_data = json.loads(data)
            res = requests.post('''%s/lab/analysis/ai/speech/text''' % (izi_lab_url), json={
                'izi_lab_api_key': self.env.company.izi_lab_api_key,
                'data': res_data,
            }, timeout=120)
            res = res.json()
            if res.get('result') and res.get('result').get('status') == 200 and res.get('result').get('ai_speech_text'):
                ai_speech_text = res.get('result').get('ai_speech_text')
                result.update({'ai_speech_text': ai_speech_text})
            elif res.get('result') and res.get('result').get('status') and res.get('result').get('status') != 200:
                result = {
                    'status': res.get('result').get('status'),
                    'message': res.get('result').get('message') or '',
                }
        except Exception as e:
            result = {
                'status': 400,
                'message': str(e),
            }
        return result

    def action_get_lab_speech_ai(self):
        result = {
            'status': 200,
            'ai_speech': False,
        }
        izi_lab_url = self.env['ir.config_parameter'].sudo().get_param('izi_lab_url')
        if not izi_lab_url:
            raise UserError(_('Please set IZI Lab URL in System Parameters.'))
        analysis_name = self.name
        visual_type_name = self.visual_type_id.name
        try:
            res = requests.post('''%s/lab/analysis/ai/speech''' % (izi_lab_url), json={
                'izi_lab_api_key': self.env.company.izi_lab_api_key,
                'analysis_name': analysis_name,
                'visual_type_name': visual_type_name,
                'data': self.ai_analysis_text,
            }, timeout=120)
            res = res.json()
            if res.get('result') and res.get('result').get('status') == 200 and res.get('result').get('ai_speech'):
                ai_speech = res.get('result').get('ai_speech')
                result.update({'ai_speech': ai_speech})
            elif res.get('result') and res.get('result').get('status') and res.get('result').get('status') != 200:
                result = {
                    'status': res.get('result').get('status'),
                    'message': res.get('result').get('message') or '',
                }
        except Exception as e:
            pass
        return result
    
    def action_get_lab_script(self, script_type, origin_code, origin_after_code, num_of_space, last_generated_code, last_error_message):
        result = {
            'status': 200,
            'code': '',
        }
        izi_lab_url = self.env['ir.config_parameter'].sudo().get_param('izi_lab_url')
        if not izi_lab_url:
            raise UserError(_('Please set IZI Lab URL in System Parameters.'))
        try:
            res = requests.post('''%s/lab/analysis/script''' % (izi_lab_url), json={
                'izi_lab_api_key': self.env.company.izi_lab_api_key,
                'script_type': script_type,
                'origin_code': origin_code,
                'last_generated_code': last_generated_code,
                'last_error_message': last_error_message,
            }, timeout=120)
            res = res.json()
            if res.get('result') and res.get('result').get('status') == 200 and res.get('result').get('code'):
                code = res.get('result').get('code')
                if code and type(code) == str:
                    code = code.replace('```python\n', '')
                    code = code.replace('```javascript\n', '')
                    code = code.replace('```sql\n', '')
                    code = code.replace('```python', '')
                    code = code.replace('```javascript', '')
                    code = code.replace('```sql', '')
                    code = code.replace('```', '')
                    code = code.replace('python', '')
                    code = code.replace('javascript', '')
                    code = code.replace('sql', '')
                    code = code.replace('**', '')
                result['code'] = code
                result['popup'] = False
                if last_generated_code and last_error_message:
                    result['popup'] = True
            elif res.get('result') and res.get('result').get('status') and res.get('result').get('status') != 200:
                result = {
                    'status': res.get('result').get('status'),
                    'message': res.get('result').get('message') or '',
                }
        except Exception as e:
            result = {
                'status': 400,
                'message': str(e),
            }
        return result
        