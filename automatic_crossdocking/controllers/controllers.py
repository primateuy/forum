# -*- coding: utf-8 -*-
# from odoo import http


# class AutomatizacionReglasAbastecimiento(http.Controller):
#     @http.route('/automatizacion_reglas_abastecimiento/automatizacion_reglas_abastecimiento', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/automatizacion_reglas_abastecimiento/automatizacion_reglas_abastecimiento/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('automatizacion_reglas_abastecimiento.listing', {
#             'root': '/automatizacion_reglas_abastecimiento/automatizacion_reglas_abastecimiento',
#             'objects': http.request.env['automatizacion_reglas_abastecimiento.automatizacion_reglas_abastecimiento'].search([]),
#         })

#     @http.route('/automatizacion_reglas_abastecimiento/automatizacion_reglas_abastecimiento/objects/<model("automatizacion_reglas_abastecimiento.automatizacion_reglas_abastecimiento"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('automatizacion_reglas_abastecimiento.object', {
#             'object': obj
#         })

