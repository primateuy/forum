# -*- coding: utf-8 -*-
# Copyright 2022 IZI PT Solusi Usaha Mudah

from odoo import http, fields
from datetime import datetime, timedelta
from odoo.http import request
import json
import string
import random
import ast
def token_generator(size=32, chars=string.ascii_lowercase + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))

from odoo.exceptions import AccessError
from odoo.service import security
from odoo.addons.web.controllers.utils import ensure_db,  is_user_internal
from odoo.addons.web.controllers.home import Home


class IZIHomeController(Home):
    @http.route('/web', type='http', auth="none")
    def web_client(self, s_action=None, **kw):

        # Ensure we have both a database and a user
        ensure_db()
        if not request.session.uid:
            return request.redirect_query('/web/login', query=request.params, code=303)
        if kw.get('redirect'):
            return request.redirect(kw.get('redirect'), 303)
        if not security.check_session(request.session, request.env):
            raise http.SessionExpiredException("Session expired")
        if not is_user_internal(request.session.uid):
            return request.redirect('/web/login_successful', 303)

        # Side-effect, refresh the session lifetime
        request.session.touch()

        # Restore the user on the environment, it was lost due to auth="none"
        request.update_env(user=request.session.uid)
        try:
            context = request.env['ir.http'].webclient_rendering_context()
            response = request.render('web.webclient_bootstrap', qcontext=context)
            response.headers['X-Frame-Options'] = 'SAMEORIGIN'
            return response
        except AccessError:
            return request.redirect('/web/login?error=access')
class DashboardWebsiteController(http.Controller):
    def make_error_response(self, status, error, error_descrip):
        return request.make_response(json.dumps({
            'data': {
                'error': error,
                'error_descrip': error_descrip,
            },
            'code': status,
        }, default=str), headers=[
            ('Content-Type', 'application/json'),
        ])

    def make_valid_response(self, body):
        return request.make_response(json.dumps({
            'data': body,
            'code': 200
        }, default=str), headers=[
            ('Content-Type', 'application/json'),
        ])
    
    @http.route('/izi/dashboard/<int:dashboard_id>/token', auth='public', type='http', cors='*', csrf=False)
    def get_access_token(self, dashboard_id, **kw):
        # Get System Parameter: Access Key
        access_key = request.env['ir.config_parameter'].sudo().get_param('izi_dashboard.access_key')
        if not access_key:
            return self.make_error_response(500, 'Error', 'Access Key is not set. Dashboard access is not allowed!')
        # Get HTTP Headers Access Key
        request_access_key = request.httprequest.headers.get('Access-Key', '')
        if request_access_key != access_key:
            return self.make_error_response(401, 'Unauthorized', 'Access Key is Not Valid')
        
        # Whitelist IP Address
        ip_address = request.httprequest.remote_addr
        whitelist_ip_addresses = request.env['ir.config_parameter'].sudo().get_param('izi_dashboard.whitelist_ip_addresses')
        if whitelist_ip_addresses:
            whitelist_ip_addresses = whitelist_ip_addresses.split(',')
            whitelist_ip_addresses = [ip.strip() for ip in whitelist_ip_addresses]
            if ip_address not in whitelist_ip_addresses:
                return self.make_error_response(401, 'Unauthorized', 'IP Address is Not Allowed')
        
        # If Valid, Generate Access Token
        # Generate 16 character Random String
        # Expired in 1 Hour
        access_token = request.env['izi.dashboard.token'].sudo().create({
            'name': 'Dashboard Access Token',
            'token': token_generator(),
            'is_active': True,
            'dashboard_id': int(dashboard_id),
            'expired_date': fields.Datetime.now() + timedelta(hours=1),
        })
        return self.make_valid_response({
            'access_token': access_token.token,
            'expired_date': access_token.expired_date,
        })
    
    @http.route('/izi/dashboard/<int:dashboard_id>/page', auth='public', type='http', website=True, cors='*', csrf=False)
    def get_dashboard_page(self, dashboard_id, **kw):
        access_token = request.env['izi.dashboard.token'].sudo().search([('expired_date', '>=', fields.Datetime.now()), ('dashboard_id', '=', dashboard_id), ('is_active', '=', True), ('token', '=', kw.get('access_token', ''))], limit=1)
        if not access_token:
            return self.make_error_response(401, 'Unauthorized', 'Invalid or Expired Access Token')
        token_user_id = access_token.user_id
        context = access_token.context
        context = ast.literal_eval(context)
        dashboard_name = request.env['izi.dashboard'].with_user(token_user_id).with_context(context).search([('id', '=', dashboard_id)]).name
        return request.render('izi_dashboard.dashboard_page', {
            'dashboard_id': dashboard_id,
            'dashboard_name': dashboard_name,
            'access_token': kw.get('access_token'),
        })
    
    @http.route('/izi/dashboard/<int:dashboard_id>', auth='public', type='http', cors='*', csrf=False)
    def get_dashboard(self, dashboard_id, **kw):
        # Get System Parameter
        access_token = request.env['izi.dashboard.token'].sudo().search([('expired_date', '>=', fields.Datetime.now()), ('dashboard_id', '=', dashboard_id), ('is_active', '=', True), ('token', '=', kw.get('access_token', ''))], limit=1)
        if not access_token:
            return self.make_error_response(401, 'Unauthorized', 'Invalid or Expired Access Token')
        # access_token.is_active = False
        request.env.cr.commit()
        
        token_user_id = access_token.user_id
        context = access_token.context
        context = ast.literal_eval(context)

        if not dashboard_id:
            return self.make_error_response(500, 'Error', 'Dashboard ID is Required')
        dashboard = request.env['izi.dashboard'].with_user(token_user_id).with_context(context).browse(dashboard_id)
        # Search Read Dashboard Block By Dashboard Id
        blocks = request.env['izi.dashboard.block'].with_user(token_user_id).with_context(context).search_read(
            domain=[['dashboard_id', '=', dashboard_id]],
            fields=[
                'id', 
                'gs_x', 
                'gs_y', 
                'gs_w',
                'gs_h',
                'min_gs_w',
                'min_gs_h',
                'analysis_id',
                'animation',
                'refresh_interval',
                'visual_type_name',
                'rtl',
            ],
        )
        # get date filters
        filters = {
            'date_format': '',
            'date_range': [],
            'dynamic': [],
        }
        date_format = dashboard.date_format
        if date_format:
            filters['date_format'] = date_format
            if date_format == 'custom':
                start_date = datetime.strftime(dashboard.start_date, '%Y-%m-%d')
                end_date = datetime.strftime(dashboard.end_date, '%Y-%m-%d')
                filters['date_range'] = [start_date, end_date] 
        # get all themes
        dashboard_themes = request.env['izi.dashboard.theme'].with_user(token_user_id).with_context(context).search([], order='name asc')
        themes = [{'id': theme.id, 'name': theme.name} for theme in dashboard_themes]
        data = {
            'theme_name': dashboard.theme_name,
            'themes': themes,
            'blocks': blocks,
            'filters': filters,
        }
        return self.make_valid_response(data)

    @http.route('/izi/analysis/<int:analysis_id>/ui_get_available_fields', auth='public', type='http', cors='*', csrf=False)
    def ui_get_available_fields(self, analysis_id):
        analysis = request.env['izi.analysis'].sudo().browse(analysis_id)
        fields = analysis.ui_get_available_fields({})
        return self.make_valid_response(fields)
    
    @http.route('/izi/analysis/<int:analysis_id>/try_get_analysis_data_dashboard', auth='public', type='http', cors='*', csrf=False)
    def try_get_analysis_data_dashboard(self, analysis_id, **kw):
        access_token = request.env['izi.dashboard.token'].sudo().search([('expired_date', '>=', fields.Datetime.now()), ('is_active', '=', True), ('token', '=', kw.get('access_token', ''))], limit=1)
        if not access_token:
            return self.make_error_response(401, 'Unauthorized', 'Invalid or Expired Access Token')
        token_user_id = access_token.user_id
        context = access_token.context
        context = ast.literal_eval(context)

        analysis = request.env['izi.analysis'].with_user(token_user_id).with_context(context).browse(analysis_id)
        kwargs = {}
        if 'kwargs' in kw:
            try:
                kwargs = json.loads(kw['kwargs'])
            except json.JSONDecodeError:
                print("Failed to decode JSON:", kw['kwargs'])
        data = analysis.try_get_analysis_data_dashboard(**kwargs)
        return self.make_valid_response(data)
    @http.route('/izi/analysis/<int:analysis_id>/data', auth='public', type='http', cors='*', csrf=False)
    def get_analysis_data(self, analysis_id, **kw):
        # Get System Parameter
        access_token = request.env['izi.dashboard.token'].sudo().search([('expired_date', '>=', fields.Datetime.now()), ('is_active', '=', True), ('token', '=', kw.get('access_token', ''))], limit=1)
        if not access_token:
            return self.make_error_response(401, 'Unauthorized', 'Invalid or Expired Access Token')
        token_user_id = access_token.user_id
        context = access_token.context
        context = ast.literal_eval(context)
        if not analysis_id:
            return self.make_error_response(500, 'Error', 'Analysis ID is required')
        analysis = request.env['izi.analysis'].with_user(token_user_id).browse(analysis_id)
        if not analysis:
            return self.make_error_response(500, 'Error', 'Analysis not found')
        kw['kwargs'] = json.loads(kw['kwargs'])
        result = analysis.with_context(context).get_analysis_data_dashboard(**kw.get('kwargs', {}))
        return self.make_valid_response(result)
    
    @http.route('/izi/analysis/fields/dynamic/<int:analysis_id>', auth='public', type='http', cors='*', csrf=False)
    def ui_get_fields_dynamic(self, analysis_id, **kw):
        if not analysis_id:
            return self.make_error_response(500, 'Error', 'Analysis ID is required')
        analysis = request.env['izi.analysis'].browse(analysis_id)
        if not analysis:
            return self.make_error_response(500, 'Error', 'Analysis not found')
        kwargs = json.loads(kw['kwargs'])
        params = kwargs['params']
        term = kwargs['query_term']
        result = analysis.ui_get_fields_dynamic(params, term)
        return self.make_valid_response(result)

    @http.route('/izi/dashboard/filters/<int:dashboard_id>', auth='user', csrf=False, website=True, save_session=False)
    def fetch_by_dashboard(self, dashboard_id, **kw):
        dashboard_filter_obj = request.env['izi.dashboard.filter']
        result = dashboard_filter_obj.fetch_by_dashboard(dashboard_id)
        return self.make_valid_response(result)
    
    @http.route('/izi/dashboard/filters/values', auth='user', csrf=False, website=True, save_session=False)
    def fetch_values(self, **kw):
        kwargs = json.loads(kw['kwargs'])
        params = kwargs['params']
        query_term = kwargs['query_term']

        dashboard_filter_obj = request.env['izi.dashboard.filter']
        result = dashboard_filter_obj.fetch_values(params, query_term)
        return self.make_valid_response(result) 

    @http.route('/izi/dashboard/slide/<int:dashboard_id>', auth='user', csrf=False, website=True, save_session=False)
    def show_slide(self, dashboard_id, **kw):
        dashboard = request.env['izi.dashboard'].sudo().browse(dashboard_id)
        slides = dashboard.slide_ids.sorted(key=lambda r: r.sequence)
        vals = []
        default_bg_attachment_url = ''
        if dashboard.general_bg_file:
            default_bg_attachment_url = '/web/image/izi.dashboard/%s/general_bg_file' % (dashboard.id)

        for slide in slides:
            if slide.bg_file:
                bg_attachment_url = '/web/image/izi.dashboard.slide/%s/bg_file' % (slide.id)
            else:
                bg_attachment_url = default_bg_attachment_url

            if slide.show_logo:
                logo_url = '/web/image/res.company/%s/logo' % (request.env.company.id)
            else:
                logo_url = ''

            vals.append({
                'title': slide.slide_title,
                'layout': slide.layout,
                'chart_size': slide.chart_size/100,
                'text_size': slide.text_size/100,
                'text_content': slide.text_content,
                'text_align': slide.text_align,
                'font_size': slide.font_size,
                'font_color': slide.font_color,
                'bg_attachment_url': bg_attachment_url,
                'analysis_id': slide.analysis_id.id,
                'automatic_font_size': slide.automatic_font_size,
                'automatic_font_color': slide.automatic_font_color,
                'layout_order':slide.layout_order,
                'logo_url':logo_url,
            })
        global_vals = {
            'dashboard_id':dashboard.id,
            'transition':dashboard.transition,
            'theme':dashboard.theme or "white",
            'is_repeat':dashboard.is_repeat,
            'auto_slide':dashboard.auto_slide * 1000
        }
        return request.render('izi_dashboard.izi_dashboard_slide', {'data':vals, 'global_data':global_vals})