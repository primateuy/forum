# Copyright 2026 Primate (https://primate.uy)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""Detailed activity statement agrupado por direccion.

No reescribe ninguna consulta propia: usa las de activity y las de
outstanding. Lo que necesita es estar antes que la clase
`DetailedActivityStatement` de OCA en el MRO, porque esa clase copia
`_display_outstanding_lines_sql_q1` de `OutstandingStatement` como atributo
de clase en tiempo de import (`detailed_activity_statement.py:68` de OCA).
Sin esta herencia explicita, el reporte detallado seguiria usando la
consulta sin agrupar.
"""

from odoo import models

from .activity_statement import ActivityStatementSql
from .outstanding_statement import OutstandingSqlAddress


class DetailedActivityStatementAddress(
    OutstandingSqlAddress, ActivityStatementSql, models.AbstractModel
):
    _inherit = "report.partner_statement.detailed_activity_statement"
