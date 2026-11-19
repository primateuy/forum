# Copyright 2026 Primate (https://primate.uy)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""Agrupamiento de los estados de cuenta OCA por direccion del cliente.

El modulo `partner_statement` (OCA 17.0.1.3.0) filtra y agrupa todas sus
consultas por `account_move_line.partner_id`. En Odoo 17 ese campo siempre
vale el partner comercial (ver `_compute_partner_id` en
`account/models/account_move_line.py`, linea 480), asi que el reporte nativo
no puede separar sucursales.

Esta extension NO toca ningun dato contable. Lo unico que cambia es la clave
de agrupamiento dentro del SQL: en lugar de `l.partner_id` se usa la
direccion del asiento.

Por que se reescribe el SQL en vez de copiarlo
----------------------------------------------
En FORUM ya hay otro modulo, `fix_partner_statement` (LocalizacionUy), que
reescribe estas mismas consultas para excluir el diario y las cuentas de
diferencia de cambio. Si copiaramos el SQL de OCA le pisariamos esos filtros
y las diferencias de cambio volverian al reporte.

Por eso cada metodo llama a `super()`, toma el SQL que haya producido la
cadena de herencia (el de OCA, el de `fix_partner_statement`, o el de
cualquier modulo futuro) y le reemplaza solo la columna de agrupamiento.
La reescritura es deliberadamente estricta: si el SQL base no tiene la forma
esperada, se corta con un error en vez de devolver numeros mal agrupados.

Invariante de diseno
--------------------
La clausula WHERE no se toca: sigue filtrando por
`l.partner_id IN %(partners)s`. El juego de partners que arma el wizard
incluye siempre al partner comercial ademas de sus direcciones, y la
expresion de agrupamiento tiene un ELSE que manda al comercial cualquier
direccion que quede fuera de ese juego. Las dos cosas juntas garantizan que
ninguna linea se pierda y que la suma de los estados por direccion sea
identicamente igual al estado nativo del partner padre.
"""

import re

from odoo import _, api
from odoo.exceptions import UserError

#: Modos de agrupamiento soportados.
GROUP_MODES = ("invoice", "delivery")

#: `l.partner_id` como token suelto. El negative lookahead deja afuera la
#: aparicion del WHERE, que es la unica que no se toca.
_RE_PARTNER = re.compile(r"\bl\.partner_id\b(?!\s+IN\b)")

#: Marca el final de la lista del SELECT en las cuatro consultas afectadas.
_MARCA_FROM = "FROM account_move_line l"


class StatementAddressSql:
    """Mixin de Python puro con la reescritura del agrupamiento.

    `__slots__` vacio no es decorativo: sin el, Odoo falla al rearmar el
    registry con "object layout differs", porque reasigna `__bases__` de la
    clase del modelo y un mixin con `__dict__` propio cambia el layout.

    Se aplica a los tres modelos de reporte por separado y a proposito:
    extender solo `statement.common` no alcanza, porque los reportes lo
    heredaron por prototipo en un modulo anterior y el registry no rehace
    esas clases hijas.
    """

    __slots__ = ()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _forum_group_mode(self):
        """Modo de agrupamiento activo, o False si el reporte es el nativo."""
        mode = self.env.context.get("forum_group_address")
        return mode if mode in GROUP_MODES else False

    def _forum_addr_ids(self):
        """Direcciones que son clave valida de agrupamiento en este reporte."""
        return tuple(self.env.context.get("forum_address_ids") or ()) or (-1,)

    def _forum_partner_expr(self):
        """Expresion SQL que reemplaza a `l.partner_id` como clave de grupo.

        Los ids van como literales porque el SQL que devolvemos ya paso por
        `mogrify` y no se vuelve a parametrizar. Son enteros de la ORM, asi
        que el `int()` alcanza como saneo.
        """
        mode = self._forum_group_mode()
        ids = ",".join(str(int(i)) for i in self._forum_addr_ids())
        if mode == "delivery":
            addr = (
                "COALESCE(m.forum_shipping_partner_id, "
                "m.partner_shipping_id, m.partner_id)"
            )
        else:
            addr = "COALESCE(m.forum_address_partner_id, m.partner_id)"
        return f"CASE WHEN {addr} IN ({ids}) THEN {addr} ELSE l.partner_id END"

    def _forum_reescribir_sql(self, sql, metodo):
        """Cambia la clave de agrupamiento del SQL que devolvio `super()`.

        Args:
            sql: la consulta ya armada por la cadena de herencia.
            metodo: nombre del metodo, solo para el mensaje de error.

        Returns:
            La misma consulta con la direccion como clave de agrupamiento.
        """
        if not self._forum_group_mode():
            return sql

        def fallar(motivo):
            raise UserError(
                _(
                    "No se pudo agrupar el estado de cuenta por direccion: la "
                    "consulta base de %(metodo)s no tiene la forma esperada "
                    "(%(motivo)s).\n\nProbablemente se actualizo "
                    "partner_statement o fix_partner_statement. Revisar "
                    "forum_partner_statement_address antes de seguir usando "
                    "el agrupamiento por direccion.",
                    metodo=metodo,
                    motivo=motivo,
                )
            )

        if "account_move m" not in sql:
            fallar("no se encontro el join a account_move con alias m")
        corte_from = sql.find(_MARCA_FROM)
        if corte_from == -1:
            fallar(f"no se encontro '{_MARCA_FROM}'")
        corte_group = sql.rfind("GROUP BY")
        if corte_group == -1 or corte_group < corte_from:
            fallar("no se encontro la clausula GROUP BY")

        expr = self._forum_partner_expr()
        seleccion, cuerpo, agrupado = (
            sql[:corte_from],
            sql[corte_from:corte_group],
            sql[corte_group:],
        )
        seleccion, n_sel = _RE_PARTNER.subn(f"{expr} AS partner_id", seleccion)
        agrupado, n_grp = _RE_PARTNER.subn(expr, agrupado)
        if n_sel != 1:
            fallar(f"se esperaba 1 l.partner_id en el SELECT y hay {n_sel}")
        if n_grp < 1:
            fallar("no hay ningun l.partner_id en el GROUP BY")
        return seleccion + cuerpo + agrupado

    # ------------------------------------------------------------------
    # Encabezado del reporte
    # ------------------------------------------------------------------
    def _get_invoice_address(self, part):
        """En modo agrupado cada hoja es una direccion: se imprime esa."""
        if self._forum_group_mode():
            return part
        return super()._get_invoice_address(part)

    # ------------------------------------------------------------------
    # Entrada: pasa el modo elegido al contexto que leen las consultas
    # ------------------------------------------------------------------
    @api.model
    def _get_report_values(self, docids, data=None):
        mode = (data or {}).get("forum_group_address")
        if mode in GROUP_MODES:
            self = self.with_context(
                forum_group_address=mode,
                forum_address_ids=tuple(data.get("forum_address_ids") or ()),
            )
        return super()._get_report_values(docids, data)

    # ------------------------------------------------------------------
    # Aging buckets  (statement.common._show_buckets_sql_q1)
    # ------------------------------------------------------------------
    def _show_buckets_sql_q1(self, partners, date_end, account_type):
        return self._forum_reescribir_sql(
            super()._show_buckets_sql_q1(partners, date_end, account_type),
            "_show_buckets_sql_q1",
        )
