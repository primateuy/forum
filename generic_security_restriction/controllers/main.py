import logging

from werkzeug import urls

from odoo import http
from odoo.http import request

from odoo.addons.web.controllers.home import Home, ensure_db

_logger = logging.getLogger(__name__)

NO_PHRASES = ('', '0', 'false', 'n', 'no', 'f', 'off')
# Debug enabled if in query parameters debug equal to:
# '1',  'assets', 'assets,tests' or any other phrases
# Example: debug=true, debug=True, debug=1, debug=abcdef etc.


class GenericSecurityRestrictionHome(Home):

    @http.route()
    def web_client(self, s_action=None, **kw):
        ensure_db()
        debug_mode = kw.get('debug', request.session.debug)

        # Phrases are discovered experimentally, because the original source
        # or method that converts the phrase from the query parameters
        # has not yet been found.
        if debug_mode.lower() in NO_PHRASES:
            return super(GenericSecurityRestrictionHome, self).web_client(
                s_action=s_action, **kw)

        if not http.request.env['res.users']._gsr_is_debug_mode_allowed(
                http.request.session.uid):
            # Clear debug mode from session
            request.session.debug = ''

            url = urls.url_parse(http.request.httprequest.url)
            url_params = url.decode_query()
            url_params = url_params.to_dict()
            url_params.pop('debug', None)
            url_local = url.replace(
                scheme='', netloc='',
                query=urls.url_encode(url_params),
            ).to_url()

            return request.redirect(url_local)

        return super(GenericSecurityRestrictionHome, self).web_client(
            s_action=s_action, **kw)
