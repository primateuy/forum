# Copyright 2026 Primate (https://primate.uy)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""Outstanding statement agrupado por direccion."""

from odoo import models

from .statement_address_mixin import StatementAddressSql


class OutstandingSqlAddress(StatementAddressSql):
    """Se define aparte porque el reporte detallado tambien usa esta consulta."""

    __slots__ = ()

    def _display_outstanding_lines_sql_q1(self, partners, date_end, account_type):
        return self._forum_reescribir_sql(
            super()._display_outstanding_lines_sql_q1(
                partners, date_end, account_type
            ),
            "_display_outstanding_lines_sql_q1",
        )


class OutstandingStatementAddress(OutstandingSqlAddress, models.AbstractModel):
    _inherit = "report.partner_statement.outstanding_statement"
