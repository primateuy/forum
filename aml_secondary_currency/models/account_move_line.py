# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    secondary_currency_id = fields.Many2one(comodel_name='res.currency', string='Divisa secundaria',
                                            related='company_id.secondary_currency_id')
    tipo_cambio = fields.Float(string='TC')
    amount_secondary = fields.Monetary(string='Importe Divisa Secundaria', currency_field='secondary_currency_id')

    def compute_amount_secondary(self):
        for rec in self:
            # Parámetros de búsqueda
            fecha = rec.move_id.date
            currency_id = self.env.companies.secondary_currency_id.id

            # Buscar todos los tipos de cambio en esa fecha
            tipos_cambio_fecha = self.env['res.currency.rate'].search([('name', '=', fecha)])

            # Buscar específicamente el tipo de cambio que necesitamos
            tipo_cambio = tipos_cambio_fecha.filtered(lambda r: r.currency_id.id == currency_id)

            if tipo_cambio:
                tipo_cambio = tipo_cambio[0]  # Tomar el primero si hay varios
                debit_credit = rec.debit or (rec.credit * -1)
                rec.amount_secondary = debit_credit * tipo_cambio.rate
                rec.tipo_cambio = tipo_cambio.inverse_company_rate
            else:
                rec.amount_secondary = 0
                if not tipos_cambio_fecha:
                    raise UserError(_(f"No se encontró tipo de cambio para la fecha {rec.move_id.date} y moneda {self.env.companies.secondary_currency_id.name} (en el asiento: {rec.move_name} con cuenta: {rec.account_id.name} "))
                else:
                    raise UserError(_(f"No se configuro la moneda secundaria, en el formulario de la empresa se configura la moneda secundaria"))
