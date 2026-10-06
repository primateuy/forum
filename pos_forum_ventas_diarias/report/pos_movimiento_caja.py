# -*- coding: utf-8 -*-
"""
Reporte unificado de movimientos de caja del punto de venta.

Junta en una sola tabla lo que en Odoo vive en tres modelos distintos:

- las ventas, que son los pagos de las órdenes (pos.payment),
- los movimientos de efectivo, que el POS registra como líneas de extracto
  (account.bank.statement.line ligadas a la sesión),
- y los saldos declarados al abrir y cerrar cada sesión (pos.session).

Es un modelo de solo lectura sobre una vista SQL: no duplica datos ni crea
tablas propias, lee siempre de los registros originales.
"""

import logging

from odoo import fields, models, tools

_logger = logging.getLogger(__name__)


class PosMovimientoCaja(models.Model):
    """
    Vista SQL que unifica ventas, movimientos de efectivo y saldos de sesión.

    Cada fila lleva un tipo que indica de cuál de las tres fuentes viene. Los
    campos propios de una venta (cliente, sello, orden, transacción) quedan
    vacíos en las filas de caja, y viceversa.
    """

    _name = 'pos.forum.movimiento.caja'
    _inherit = ['pos.forum.date.local.mixin']
    _description = 'Movimientos de caja del punto de venta'
    _auto = False
    _rec_name = 'concepto'
    _order = 'date desc, id desc'

    # Campo de origen para el día calendario local del mixin.
    _date_local_source = 'date'

    # ------------------------------------------------------------------
    # Comunes a todas las fuentes
    # ------------------------------------------------------------------

    date = fields.Datetime(string='Fecha', readonly=True)
    tipo = fields.Selection(
        selection=[
            ('apertura', 'Apertura de caja'),
            ('venta', 'Venta'),
            ('ingreso', 'Ingreso de efectivo'),
            ('retiro', 'Retiro de efectivo'),
            ('diferencia', 'Diferencia de caja'),
            ('cierre', 'Cierre de caja'),
        ],
        string='Tipo',
        readonly=True,
    )
    concepto = fields.Char(
        string='Concepto',
        readonly=True,
        help='Forma de pago en las ventas, motivo del movimiento en el efectivo.',
    )
    amount = fields.Monetary(
        string='Importe',
        currency_field='currency_id',
        readonly=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Moneda',
        readonly=True,
    )
    config_id = fields.Many2one(
        comodel_name='pos.config',
        string='Punto de venta',
        readonly=True,
    )
    session_id = fields.Many2one(
        comodel_name='pos.session',
        string='Sesión',
        readonly=True,
    )
    user_id = fields.Many2one(
        comodel_name='res.users',
        string='Cajero',
        readonly=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Compañía',
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Propios de las ventas
    # ------------------------------------------------------------------

    payment_method_id = fields.Many2one(
        comodel_name='pos.payment.method',
        string='Forma de pago',
        readonly=True,
    )
    pos_order_id = fields.Many2one(
        comodel_name='pos.order',
        string='Orden',
        readonly=True,
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Cliente',
        readonly=True,
    )
    issuer_name = fields.Char(string='Sello', readonly=True)
    installments = fields.Integer(string='Cuotas', readonly=True)
    payment_transaction_id = fields.Many2one(
        comodel_name='payment.transaction',
        string='Transacción de pago',
        readonly=True,
    )

    def init(self):
        """
        Crea la vista SQL que alimenta el reporte.

        El identificador se genera con row_number porque las tres fuentes
        tienen sus propias secuencias y sus ids se pisarían entre sí.

        La fecha de los movimientos de efectivo se toma del asiento: la línea
        de extracto hereda de account.move y no tiene columna propia de fecha.

        Los movimientos de efectivo se clasifican por el signo del importe y
        no por el texto de la referencia: el POS arma esa referencia con el
        tipo ya traducido, así que buscar «in» u «out» dejaría de funcionar
        en una instancia en español.
        """
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                WITH movimientos AS (

                    -- Ventas: un renglón por cada pago de una orden
                    SELECT
                        'venta'::varchar            AS tipo,
                        pay.payment_date            AS date,
                        pm.name->>'en_US'           AS concepto,
                        pay.amount                  AS amount,
                        pay.config_id               AS config_id,
                        pay.session_id              AS session_id,
                        pay.user_id                 AS user_id,
                        pay.company_id              AS company_id,
                        pay.payment_method_id       AS payment_method_id,
                        pay.pos_order_id            AS pos_order_id,
                        ord.partner_id              AS partner_id,
                        pay.issuer_name             AS issuer_name,
                        pay.installments            AS installments,
                        pay.payment_transaction_id  AS payment_transaction_id
                    FROM pos_payment pay
                    JOIN pos_order ord ON ord.id = pay.pos_order_id
                    LEFT JOIN pos_payment_method pm ON pm.id = pay.payment_method_id

                    UNION ALL

                    -- Efectivo entrante y saliente, y el ajuste del cierre
                    SELECT
                        CASE
                            WHEN stl.payment_ref ILIKE '%%iferencia%%' THEN 'diferencia'
                            WHEN stl.amount < 0 THEN 'retiro'
                            ELSE 'ingreso'
                        END::varchar                AS tipo,
                        mv.date::timestamp          AS date,
                        stl.payment_ref             AS concepto,
                        stl.amount                  AS amount,
                        ses.config_id               AS config_id,
                        stl.pos_session_id          AS session_id,
                        ses.user_id                 AS user_id,
                        cfg.company_id              AS company_id,
                        NULL::integer               AS payment_method_id,
                        NULL::integer               AS pos_order_id,
                        stl.partner_id              AS partner_id,
                        NULL::varchar               AS issuer_name,
                        NULL::integer               AS installments,
                        NULL::integer               AS payment_transaction_id
                    FROM account_bank_statement_line stl
                    JOIN account_move mv ON mv.id = stl.move_id
                    JOIN pos_session ses ON ses.id = stl.pos_session_id
                    JOIN pos_config cfg ON cfg.id = ses.config_id

                    UNION ALL

                    -- Saldo declarado al abrir la sesión
                    SELECT
                        'apertura'::varchar         AS tipo,
                        ses.start_at                AS date,
                        'Saldo inicial'::varchar    AS concepto,
                        ses.cash_register_balance_start AS amount,
                        ses.config_id, ses.id, ses.user_id, cfg.company_id,
                        NULL::integer, NULL::integer, NULL::integer,
                        NULL::varchar, NULL::integer, NULL::integer
                    FROM pos_session ses
                    JOIN pos_config cfg ON cfg.id = ses.config_id
                    WHERE ses.cash_register_balance_start IS NOT NULL
                      AND ses.cash_register_balance_start <> 0

                    UNION ALL

                    -- Saldo contado al cerrar. Solo de sesiones ya cerradas:
                    -- en una sesión abierta el campo todavía no significa nada.
                    SELECT
                        'cierre'::varchar           AS tipo,
                        COALESCE(ses.stop_at, ses.start_at) AS date,
                        'Saldo final contado'::varchar AS concepto,
                        ses.cash_register_balance_end_real AS amount,
                        ses.config_id, ses.id, ses.user_id, cfg.company_id,
                        NULL::integer, NULL::integer, NULL::integer,
                        NULL::varchar, NULL::integer, NULL::integer
                    FROM pos_session ses
                    JOIN pos_config cfg ON cfg.id = ses.config_id
                    WHERE ses.state = 'closed'
                      AND ses.cash_register_balance_end_real IS NOT NULL
                      AND ses.cash_register_balance_end_real <> 0
                )
                SELECT
                    row_number() OVER (ORDER BY m.date DESC, m.tipo) AS id,
                    m.*,
                    comp.currency_id AS currency_id
                FROM movimientos m
                LEFT JOIN res_company comp ON comp.id = m.company_id
            )
        """ % self._table)
