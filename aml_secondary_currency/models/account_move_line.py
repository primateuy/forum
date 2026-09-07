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
    # Cálculo de divisa secundaria
    # -------------------------------------------------------------------------
    def _get_secondary_rate(self, sec_currency, date):
        """Devuelve la cotización vigente de la divisa secundaria a una fecha.

        Busca la última cotización cargada con fecha menor o igual a `date`
        -mismo criterio que usa el core de Odoo para convertir importes- en
        lugar de exigir una cotización cargada exactamente ese día. Así un
        asiento de un sábado, un feriado o un día sin carga toma el último
        tipo de cambio conocido en vez de quedar sin valor.

        Args:
            sec_currency (res.currency): divisa secundaria de la empresa.
            date (date): fecha contable del asiento.

        Returns:
            res.currency.rate: cotización vigente, o recordset vacío si no
                existe ninguna cotización anterior o igual a esa fecha.
        """
        if not sec_currency or not date:
            return self.env['res.currency.rate']
        return self.env['res.currency.rate'].search([
            ('currency_id', '=', sec_currency.id),
            ('name', '<=', date),
        ], order='name desc', limit=1)

    def _apply_secondary_currency(self, strict=False):
        """Calcula `amount_secondary` y `tipo_cambio` sobre las líneas de `self`.

        El importe en divisa secundaria es un dato informativo: no debe frenar
        la contabilización de una venta, una factura o una amortización. Por eso
        el modo por defecto no interrumpe el flujo.

        Args:
            strict (bool): si es True lanza UserError cuando falta la divisa
                secundaria o la cotización. Si es False (default) deja los
                importes en 0, registra un warning y sigue adelante.

        Raises:
            UserError: solo en modo estricto (invocación explícita del usuario
                desde el wizard), cuando falta configuración o cotización.
        """
        # Agrupar líneas por (divisa secundaria, fecha) para minimizar queries
        grouped = {}
        for line in self:
            sec_currency = line.company_id.secondary_currency_id
            if not sec_currency:
                line.amount_secondary = 0.0
                line.tipo_cambio = 0.0
                continue
            key = (sec_currency.id, line.move_id.date)
            grouped.setdefault(key, self.env['account.move.line'])
            grouped[key] |= line

        if strict and self and not grouped:
            raise UserError(_(
                "No se configuró la moneda secundaria. "
                "En el formulario de la empresa se configura la moneda secundaria."
            ))

        missing = []
        for (sec_currency_id, date), lines in grouped.items():
            sec_currency = self.env['res.currency'].browse(sec_currency_id)
            rate_record = self._get_secondary_rate(sec_currency, date)
            if not rate_record:
                missing.append((date, sec_currency, lines[:1]))
                for line in lines:
                    line.amount_secondary = 0.0
                    line.tipo_cambio = 0.0
                continue
            for line in lines:
                debit_credit = line.debit or (line.credit * -1)
                line.amount_secondary = debit_credit * rate_record.rate
                line.tipo_cambio = rate_record.inverse_company_rate

        if missing:
            detalle = "\n".join(
                _("- Fecha %(fecha)s, moneda %(moneda)s "
                  "(asiento: %(asiento)s, cuenta: %(cuenta)s)") % {
                    'fecha': date,
                    'moneda': sec_currency.name,
                    'asiento': sample.move_name,
                    'cuenta': sample.account_id.name,
                }
                for date, sec_currency, sample in missing
            )
            if strict:
                raise UserError(_(
                    "No se encontró tipo de cambio para:\n%s"
                ) % detalle)
            _logger.warning(
                "aml_secondary_currency: sin tipo de cambio, importe en divisa "
                "secundaria dejado en 0 para:\n%s", detalle,
            )

    @api.depends('debit', 'credit', 'move_id.date', 'company_id.secondary_currency_id')
    def _compute_amount_secondary(self):
        """Calcula el importe en divisa secundaria de forma automática.

        Se dispara cada vez que cambian los montos (debit/credit), la fecha del
        asiento o la divisa secundaria de la empresa, en todos los flujos:
        _post(), conciliación bancaria, escritura directa de líneas, etc. Nunca
        lanza excepciones: un dato informativo no puede frenar una operación.
        """
        self._apply_secondary_currency(strict=False)

    def compute_amount_secondary(self):
        """Método legacy: fuerza el recálculo de divisa secundaria.

        Se mantiene por compatibilidad con el wizard y con `_post()`. No
        interrumpe el flujo: si falta la cotización solo registra un warning y
        deja los importes en 0, para que puedan recalcularse después con el
        wizard una vez cargado el tipo de cambio.
        """
        self._apply_secondary_currency(strict=False)

    # -------------------------------------------------------------------------
    # Fecha del tipo de cambio en asientos manuales
    # -------------------------------------------------------------------------
    def _get_rate_date(self):
        """
        Determina la fecha usada para convertir importes en divisa a la moneda
        de la empresa (campo `currency_rate`).

        El core de Odoo prioriza `invoice_date` sobre `date`:
            invoice_date or date or hoy

        En esta instancia el módulo `l10n_uy_einvoice_base` define
        `invoice_date` con `default=fields.Date.context_today`, por lo que TODO
        asiento -incluidos los manuales (`move_type='entry'`)- queda con
        `invoice_date = hoy`. Eso hacía que un asiento manual con fecha contable
        31/10 convirtiera las líneas en divisa usando la cotización de HOY en
        lugar de la del 31/10, descuadrando el asiento al publicar.

        Para asientos que NO son facturas, la fecha de conversión debe ser
        siempre la fecha contable del asiento (`move_id.date`), ignorando
        `invoice_date`. En facturas se mantiene el comportamiento del core.
        """
        self.ensure_one()
        if self.move_id and not self.move_id.is_invoice(include_receipts=True):
            return self.move_id.date or fields.Date.context_today(self)
        return super()._get_rate_date()

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

            def changed(fname):
                # En líneas nuevas todo se considera "cambiado".
                return is_new or before_vals[fname] != after_vals[fname]

            # Derivar el balance (debe/haber en USD) desde amount_currency y la
            # cotización SOLO cuando el usuario NO fijó el balance manualmente.
            #
            # Caso de uso DLA: el usuario carga el importe en divisa (p. ej.
            # 4061,20 UYU) y además escribe el debe/haber en USD (p. ej. 100),
            # decidiendo el tipo de cambio del asiento. Antes este override
            # pisaba ese 100 con la conversión a la cotización oficial
            # (4061,20 / 39,741 = 102,192) y descuadraba el asiento. Ahora se
            # respeta el balance ingresado por el usuario.
            #
            # Solo se deriva el balance cuando cambió amount_currency o la
            # cotización (p. ej. al cambiar la fecha) y el usuario no tocó el
            # balance, o es una línea nueva sin balance. Mismo criterio que el
            # _sync_invoice del core para facturas.
            if (
                (changed('amount_currency') or changed('currency_rate'))
                and not self.env.is_protected(self._fields['balance'], line)
                and (not changed('balance') or (is_new and not after_vals['balance']))
            ):
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
