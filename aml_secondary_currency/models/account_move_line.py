# -*- coding: utf-8 -*-
import logging
from contextlib import contextmanager

from odoo import api, models, fields, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    secondary_currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Divisa secundaria',
        related='company_id.secondary_currency_id',
    )
    tipo_cambio = fields.Float(
        string='TC',
        compute='_compute_amount_secondary',
        store=True,
    )
    amount_secondary = fields.Monetary(
        string='Importe Divisa Secundaria',
        currency_field='secondary_currency_id',
        compute='_compute_amount_secondary',
        store=True,
    )

    # -------------------------------------------------------------------------
    # Cálculo automático de divisa secundaria
    # -------------------------------------------------------------------------
    @api.depends('debit', 'credit', 'move_id.date', 'company_id.secondary_currency_id')
    def _compute_amount_secondary(self):
        """
        Calcula el importe en divisa secundaria cada vez que cambian los montos
        (debit/credit) o la fecha del asiento.

        Se dispara automáticamente en todos los flujos: _post(), conciliación
        bancaria, escritura directa de líneas, etc.  No depende de que se
        ejecute _post().
        """
        # Agrupar líneas por (company, fecha) para minimizar queries
        grouped = {}
        for line in self:
            sec_currency = line.company_id.secondary_currency_id
            if not sec_currency:
                line.amount_secondary = 0
                line.tipo_cambio = 0
                continue
            key = (sec_currency.id, line.move_id.date)
            grouped.setdefault(key, []).append(line)

        for (sec_currency_id, fecha), lines in grouped.items():
            # Buscar tipo de cambio para esta fecha y moneda secundaria
            rate_record = self.env['res.currency.rate'].search([
                ('name', '=', fecha),
                ('currency_id', '=', sec_currency_id),
            ], limit=1)
            if rate_record:
                rate = rate_record.rate
                inverse_rate = rate_record.inverse_company_rate
                for line in lines:
                    debit_credit = line.debit or (line.credit * -1)
                    line.amount_secondary = debit_credit * rate
                    line.tipo_cambio = inverse_rate
            else:
                for line in lines:
                    line.amount_secondary = 0
                    line.tipo_cambio = 0

    def compute_amount_secondary(self):
        """
        Método legacy: fuerza el recálculo de divisa secundaria.
        Se mantiene para compatibilidad con el wizard y con _post().
        Lanza UserError si falta configuración (solo cuando se invoca
        explícitamente, no desde el compute automático).
        """
        sec_currency = self.env.companies.secondary_currency_id
        if not sec_currency:
            raise UserError(_(
                "No se configuró la moneda secundaria. "
                "En el formulario de la empresa se configura la moneda secundaria."
            ))

        # Agrupar por fecha para minimizar queries
        by_date = {}
        for rec in self:
            by_date.setdefault(rec.move_id.date, self.env['account.move.line'])
            by_date[rec.move_id.date] |= rec

        for fecha, lines in by_date.items():
            rate_record = self.env['res.currency.rate'].search([
                ('name', '=', fecha),
                ('currency_id', '=', sec_currency.id),
            ], limit=1)
            if not rate_record:
                # Tomar la primera línea para el mensaje de error
                sample = lines[0]
                raise UserError(_(
                    "No se encontró tipo de cambio para la fecha %s "
                    "y moneda %s (en el asiento: %s con cuenta: %s)."
                ) % (
                    fecha,
                    sec_currency.name,
                    sample.move_name,
                    sample.account_id.name,
                ))
            for rec in lines:
                debit_credit = rec.debit or (rec.credit * -1)
                rec.amount_secondary = debit_credit * rate_record.rate
                rec.tipo_cambio = rate_record.inverse_company_rate

    # -------------------------------------------------------------------------
    # Sincronización balance ← amount_currency para asientos manuales
    # -------------------------------------------------------------------------
    @contextmanager
    def _sync_invoice(self, container):
        """
        Extiende _sync_invoice para que, en asientos manuales (no factura) con
        líneas en moneda distinta a la de la empresa, el balance (debit/credit)
        se derive de amount_currency / currency_rate usando la fecha del asiento.

        Odoo core solo hace esta sincronización para facturas; los asientos
        manuales quedan con el balance del auto-balance que no considera el
        tipo de cambio.
        """
        # Snapshot de líneas manuales multi-moneda ANTES del cambio
        def _manual_mc_snapshot():
            return {
                line: {
                    'amount_currency': line.currency_id.round(line.amount_currency),
                    'balance': line.company_id.currency_id.round(line.balance),
                    'currency_rate': line.currency_rate,
                }
                for line in container['records'].with_context(
                    skip_invoice_line_sync=True,
                ).filtered(
                    lambda l: (
                        not l.move_id.is_invoice(include_receipts=True)
                        and l.currency_id
                        and l.currency_id != l.company_currency_id
                    )
                )
            }

        before_manual = _manual_mc_snapshot()

        # Ejecutar el sync original del core (maneja facturas)
        with super()._sync_invoice(container):
            yield

        # Post-procesamiento: sincronizar balance para asientos manuales
        after_manual = _manual_mc_snapshot()

        for line, after_vals in after_manual.items():
            if not after_vals['amount_currency'] or not after_vals['currency_rate']:
                continue

            before_vals = before_manual.get(line)
            is_new = before_vals is None

            # Recalcular si la línea es nueva, o si cambió amount_currency o
            # currency_rate (por ejemplo al cambiar la fecha del asiento)
            if (is_new
                    or before_vals['amount_currency'] != after_vals['amount_currency']
                    or before_vals['currency_rate'] != after_vals['currency_rate']):
                new_balance = line.company_id.currency_id.round(
                    after_vals['amount_currency'] / after_vals['currency_rate']
                )
                if line.balance != new_balance:
                    line.balance = new_balance

        # Forzar recompute de debit/credit para las líneas tocadas
        if after_manual:
            manual_lines = self.env['account.move.line'].concat(
                *after_manual.keys()
            )
            self.env.add_to_compute(self._fields['debit'], manual_lines)
            self.env.add_to_compute(self._fields['credit'], manual_lines)
