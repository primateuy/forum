# -*- coding: utf-8 -*-
# from odoo import http


# class CambioPrecio(http.Controller):
#     @http.route('/cambio_precio/cambio_precio', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/cambio_precio/cambio_precio/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('cambio_precio.listing', {
#             'root': '/cambio_precio/cambio_precio',
#             'objects': http.request.env['cambio_precio.cambio_precio'].search([]),
#         })

#     @http.route('/cambio_precio/cambio_precio/objects/<model("cambio_precio.cambio_precio"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('cambio_precio.object', {
#             'object': obj
#         })

