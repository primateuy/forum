# -*- coding: utf-8 -*-
"""
Tests del tipo de cambio en asientos manuales multi-moneda.

Bug reportado en DLA: un asiento manual con fecha contable 31/10 convertía las
líneas en divisa a la moneda de la empresa (USD) usando la cotización de HOY en
lugar de la del 31/10. La causa: `l10n_uy_einvoice_base` define `invoice_date`
con `default=fields.Date.context_today`, así que todo asiento -incluidos los
manuales- queda con `invoice_date = hoy`, y el core prioriza `invoice_date`
sobre `date` en `_get_rate_date()`. El módulo corrige `_get_rate_date()` para
que los asientos que no son facturas usen siempre `move.date`.

Estos tests simulan esa condición seteando `invoice_date` a una fecha distinta
de `date`, sin depender de que LocalizacionUy esté instalada.
"""
from datetime import date

from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSecondaryCurrencyRate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company_currency = cls.company.currency_id

        # Fecha contable (31/10) vs fecha de registración / invoice_date (18/11)
        cls.date_acc = date(2025, 10, 31)
        cls.date_reg = date(2025, 11, 18)

        # Moneda extranjera de las líneas, con cotizaciones DISTINTAS en cada
        # fecha para que el error sea evidente.
        cls.foo = cls.env['res.currency'].create({
            'name': 'FOO',
            'symbol': 'F',
            'rounding': 0.01,
        })
        cls.sec = cls.env['res.currency'].create({
            'name': 'SEC',
            'symbol': 'S',
            'rounding': 0.01,
        })
        cls.company.secondary_currency_id = cls.sec.id

        cls.rate_acc = 1.5   # cotización FOO/empresa el 31/10
        cls.rate_reg = 1.0   # cotización FOO/empresa el 18/11
        cls.env['res.currency.rate'].create([
            {'name': cls.date_acc, 'currency_id': cls.foo.id,
             'rate': cls.rate_acc, 'company_id': cls.company.id},
            {'name': cls.date_reg, 'currency_id': cls.foo.id,
             'rate': cls.rate_reg, 'company_id': cls.company.id},
            {'name': cls.date_acc, 'currency_id': cls.sec.id,
             'rate': 40.0, 'company_id': cls.company.id},
            {'name': cls.date_reg, 'currency_id': cls.sec.id,
             'rate': 41.0, 'company_id': cls.company.id},
        ])

        cls.journal = cls.env['account.journal'].create({
            'name': 'Asientos Manuales Test',
            'code': 'TMISC',
            'type': 'general',
        })
        cls.acc_debit = cls.env['account.account'].create({
            'name': 'Cuenta Debe Test', 'code': 'TSTDEB',
            'account_type': 'asset_current',
        })
        cls.acc_credit = cls.env['account.account'].create({
            'name': 'Cuenta Haber Test', 'code': 'TSTCRE',
            'account_type': 'liability_current',
        })
        cls.amount_foo = 150.0

    def _make_manual_move(self, accounting_date, invoice_date=None):
        """
        Asiento manual balanceado en FOO. `invoice_date` distinto de
        `accounting_date` reproduce el default a 'hoy' de LocalizacionUy.
        """
        vals = {
            'move_type': 'entry',
            'journal_id': self.journal.id,
            'date': accounting_date,
            'line_ids': [
                Command.create({
                    'account_id': self.acc_debit.id,
                    'currency_id': self.foo.id,
                    'amount_currency': self.amount_foo,
                }),
                Command.create({
                    'account_id': self.acc_credit.id,
                    'currency_id': self.foo.id,
                    'amount_currency': -self.amount_foo,
                }),
            ],
        }
        if invoice_date:
            vals['invoice_date'] = invoice_date
        return self.env['account.move'].create(vals)

    def test_get_rate_date_ignora_invoice_date_en_manuales(self):
        """En un asiento manual, _get_rate_date() devuelve la fecha contable,
        aunque invoice_date apunte a otra fecha (default 'hoy')."""
        move = self._make_manual_move(self.date_acc, invoice_date=self.date_reg)
        for line in move.line_ids:
            self.assertEqual(
                line._get_rate_date(), self.date_acc,
                "La fecha del tipo de cambio debe ser la fecha contable del asiento")

    def test_currency_rate_usa_fecha_contable(self):
        """El currency_rate y el balance usan la cotización de la fecha
        contable (31/10), no la de invoice_date / hoy (18/11)."""
        move = self._make_manual_move(self.date_acc, invoice_date=self.date_reg)
        for line in move.line_ids:
            # currency_rate = cotización FOO/empresa del 31/10 (1,5)
            self.assertAlmostEqual(line.currency_rate, self.rate_acc, places=6)
            # balance = amount_currency / 1,5
            self.assertAlmostEqual(
                line.balance,
                self.company_currency.round(line.amount_currency / self.rate_acc),
                msg="El balance no usa la cotización de la fecha contable")
        self.assertEqual(sum(move.line_ids.mapped('balance')), 0.0)

    def test_publicar_asiento_manual_con_invoice_date_hoy(self):
        """El asiento manual se publica sin error de 'no saldado' aunque
        invoice_date sea distinto de la fecha contable."""
        move = self._make_manual_move(self.date_acc, invoice_date=self.date_reg)
        move.action_post()
        self.assertEqual(move.state, 'posted')

    def test_respeta_balance_manual_del_usuario(self):
        """
        El usuario carga el importe en divisa (150 FOO) y además escribe el
        debe/haber en USD (90), decidiendo el tipo de cambio del asiento
        (150 FOO = 90 USD, en vez de los 100 que daría la cotización oficial).
        El sistema debe RESPETAR ese balance manual y no pisarlo con la
        conversión a la cotización, para que el asiento cuadre contra la
        contralínea en USD.
        """
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal.id,
            'date': self.date_acc,
            'invoice_date': self.date_reg,
            'line_ids': [
                Command.create({
                    'account_id': self.acc_credit.id,
                    'currency_id': self.foo.id,
                    'amount_currency': -150.0,   # auto daría -100 al rate 1,5
                    'debit': 0.0,
                    'credit': 90.0,              # el usuario decide 150 FOO = 90 USD
                }),
                Command.create({
                    'account_id': self.acc_debit.id,
                    'debit': 90.0,
                    'credit': 0.0,
                }),
            ],
        })
        foreign_line = move.line_ids.filtered(lambda l: l.currency_id == self.foo)
        self.assertEqual(
            foreign_line.balance, -90.0,
            "Se pisó el balance ingresado manualmente por el usuario")
        self.assertEqual(sum(move.line_ids.mapped('balance')), 0.0,
                         "El asiento quedó descuadrado")
        move.action_post()
        self.assertEqual(move.state, 'posted')

    def test_factura_mantiene_invoice_date(self):
        """En facturas se conserva el comportamiento del core: la fecha del
        tipo de cambio sigue siendo invoice_date."""
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'invoice_date': self.date_reg,
            'date': self.date_acc,
            'partner_id': self.env['res.partner'].create({'name': 'Cliente Test'}).id,
            'currency_id': self.foo.id,
            'invoice_line_ids': [
                Command.create({
                    'name': 'Producto',
                    'quantity': 1,
                    'price_unit': 100.0,
                    'account_id': self.acc_debit.id,
                }),
            ],
        })
        line = invoice.invoice_line_ids[0]
        self.assertEqual(
            line._get_rate_date(), self.date_reg,
            "En facturas la fecha del tipo de cambio debe seguir siendo invoice_date")
