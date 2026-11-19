# Copyright 2026 Primate (https://primate.uy)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""Activity statement agrupado por direccion.

Las lineas conciliadas (`_display_activity_reconciled_lines_sql_q2`) NO se
tocan a proposito: se renderizan anidadas bajo la factura y se emparejan por
id de apunte, no por partner. Por eso un pago atribuido a la sucursal A que
cancela una factura de la sucursal B aparece bajo la factura de B, que es la
regla acordada, y sin codigo especial.
"""

from odoo import models

from .statement_address_mixin import StatementAddressSql


class ActivityStatementSql(StatementAddressSql):
    """Mixin de Python puro: lo reusa tambien el reporte detallado."""

    __slots__ = ()

    def _initial_balance_sql_q1(self, partners, date_start, account_type):
        return self._forum_reescribir_sql(
            super()._initial_balance_sql_q1(partners, date_start, account_type),
            "_initial_balance_sql_q1",
        )

    def _display_activity_lines_sql_q1(
        self, partners, date_start, date_end, account_type
    ):
        return self._forum_reescribir_sql(
            super()._display_activity_lines_sql_q1(
                partners, date_start, date_end, account_type
            ),
            "_display_activity_lines_sql_q1",
        )


class ActivityStatementAddress(ActivityStatementSql, models.AbstractModel):
    _inherit = "report.partner_statement.activity_statement"
