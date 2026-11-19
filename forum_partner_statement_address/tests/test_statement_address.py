# Copyright 2026 Primate (https://primate.uy)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""Pruebas del agrupamiento de estados de cuenta por direccion.

El invariante que importa es uno solo y se verifica en los tres reportes:
la suma de los estados por direccion tiene que dar exactamente lo mismo que
el estado nativo del partner comercial. Si eso se cumple, el desglose no
inventa ni pierde plata.
"""

from collections import defaultdict

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged

BUCKET_KEYS = ("current", "b_1_30", "b_30_60", "b_60_90", "b_90_120", "b_over_120")


@tagged("post_install", "-at_install")
class TestStatementAddress(TransactionCase):
    """Se arma sobre el plan de cuentas real de la base, no sobre el de
    `AccountTestInvoicingCommon`: esa clase intenta reconfigurar la moneda de
    la compania y falla en cuanto hay apuntes contables, que es el caso de
    cualquier base de FORUM. El diario se crea aca mismo y sin CFE, para no
    depender de la configuracion de ningun diario existente ni disparar la
    factura electronica. Todo se revierte al terminar la transaccion."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.cuenta_ingreso = cls.env["account.account"].search(
            [("company_id", "=", cls.company.id), ("account_type", "=", "income")],
            limit=1,
        )
        cls.cuenta_cobrar = cls.env["account.account"].search(
            [
                ("company_id", "=", cls.company.id),
                ("account_type", "=", "asset_receivable"),
            ],
            limit=1,
        )
        cls.diario = cls.env["account.journal"].create(
            {
                "name": "Ventas prueba direcciones",
                "code": "TSTDI",
                "type": "sale",
                "company_id": cls.company.id,
                "default_account_id": cls.cuenta_ingreso.id,
            }
        )
        if "diario_cfe" in cls.env["account.journal"]._fields:
            cls.diario.diario_cfe = False
        cls.producto = cls.env["product.product"].create(
            {"name": "Servicio demo estado de cuenta", "type": "service"}
        )
        Partner = cls.env["res.partner"]
        cls.empresa = Partner.create(
            {
                "name": "FRANQUICIAS DEMO S.A.",
                "property_account_receivable_id": cls.cuenta_cobrar.id,
            }
        )
        cls.suc_a = Partner.create(
            {"name": "Sucursal A", "type": "invoice", "parent_id": cls.empresa.id}
        )
        cls.suc_b = Partner.create(
            {"name": "Sucursal B", "type": "invoice", "parent_id": cls.empresa.id}
        )
        cls.entrega_a = Partner.create(
            {"name": "Deposito A", "type": "delivery", "parent_id": cls.empresa.id}
        )
        cls.entrega_b = Partner.create(
            {"name": "Deposito B", "type": "delivery", "parent_id": cls.empresa.id}
        )
        cls.date_start = fields.Date.from_string("2026-01-01")
        cls.date_end = fields.Date.from_string("2026-12-31")

        # Saldo inicial: una factura anterior al periodo, a la sucursal A.
        cls.inv_previa = cls._crear_factura(
            cls.suc_a, 500.0, "2025-11-15", cls.entrega_a
        )
        # Movimientos dentro del periodo.
        cls.inv_a1 = cls._crear_factura(
            cls.suc_a, 1000.0, "2026-03-10", cls.entrega_a
        )
        cls.inv_a2 = cls._crear_factura(
            cls.suc_a, 250.0, "2026-05-20", cls.entrega_a
        )
        cls.inv_b1 = cls._crear_factura(
            cls.suc_b, 700.0, "2026-04-05", cls.entrega_b
        )
        # Factura a nombre de la empresa, sin sucursal.
        cls.inv_emp = cls._crear_factura(cls.empresa, 300.0, "2026-06-01", None)
        # Nota de credito a la sucursal A.
        cls.nc_a = cls._crear_factura(
            cls.suc_a, 120.0, "2026-07-01", cls.entrega_a, move_type="out_refund"
        )

    @classmethod
    def _crear_factura(
        cls, partner, importe, fecha, entrega=None, move_type="out_invoice"
    ):
        vals = {
            "move_type": move_type,
            "journal_id": cls.diario.id,
            "partner_id": partner.id,
            "invoice_date": fields.Date.from_string(fecha),
            "date": fields.Date.from_string(fecha),
            "invoice_line_ids": [
                Command.create(
                    {
                        "product_id": cls.producto.id,
                        "name": "Servicio demo",
                        "quantity": 1,
                        "price_unit": importe,
                        "tax_ids": [],
                    }
                )
            ],
        }
        if entrega is not None:
            vals["partner_shipping_id"] = entrega.id
        move = cls.env["account.move"].create(vals)
        move.action_post()
        return move

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _reporte(self, modelo, wizard, modo, **extra):
        """Corre un reporte y devuelve el dict de `_get_report_values`."""
        vals = {
            "date_end": self.date_end,
            "company_id": self.company.id,
            "forum_group_address": modo,
            # Se desactivan los dos filtros porque esconden hojas y romperian
            # la comparacion de totales: no son parte de lo que se prueba.
            "filter_partners_non_due": False,
            "filter_negative_balances": False,
        }
        if "date_start" in self.env[wizard]._fields:
            vals["date_start"] = self.date_start
        vals.update(extra)
        wiz = (
            self.env[wizard]
            .with_context(active_ids=self.empresa.ids, model="res.partner")
            .create(vals)
        )
        data = wiz._prepare_statement()
        return self.env[modelo]._get_report_values(list(data["partner_ids"]), data)

    def _totales(self, res):
        """Suma por moneda de todas las hojas del reporte."""
        tot = defaultdict(float)
        for pdata in res["data"].values():
            for cur_id, cur in pdata["currencies"].items():
                tot[(cur_id, "balance_forward")] += cur["balance_forward"]
                tot[(cur_id, "amount_due")] += cur["amount_due"]
                tot[(cur_id, "ending_balance")] += cur["ending_balance"]
                buckets = cur.get("buckets") or {}
                if buckets:
                    for key in BUCKET_KEYS:
                        tot[(cur_id, key)] += buckets.get(key) or 0.0
        return tot

    def _comparar(self, modelo, wizard):
        """Nativo vs. agrupado por facturacion vs. agrupado por entrega."""
        nativo = self._totales(self._reporte(modelo, wizard, "none"))
        por_fact = self._totales(self._reporte(modelo, wizard, "invoice"))
        por_entrega = self._totales(self._reporte(modelo, wizard, "delivery"))
        self.assertTrue(nativo, "El reporte nativo no devolvio ningun total")
        for clave, valor in nativo.items():
            self.assertAlmostEqual(
                por_fact.get(clave, 0.0),
                valor,
                places=2,
                msg=f"{modelo}: facturacion no cuadra en {clave}",
            )
            self.assertAlmostEqual(
                por_entrega.get(clave, 0.0),
                valor,
                places=2,
                msg=f"{modelo}: entrega no cuadra en {clave}",
            )
        self.assertEqual(
            set(nativo), set(por_fact), f"{modelo}: aparecieron claves de mas"
        )
        return nativo

    # ------------------------------------------------------------------
    # Pruebas
    # ------------------------------------------------------------------
    def test_01_activity_suma_igual_al_nativo(self):
        self._comparar(
            "report.partner_statement.activity_statement",
            "activity.statement.wizard",
        )

    def test_02_outstanding_suma_igual_al_nativo(self):
        self._comparar(
            "report.partner_statement.outstanding_statement",
            "outstanding.statement.wizard",
        )

    def test_03_detailed_suma_igual_al_nativo(self):
        self._comparar(
            "report.partner_statement.detailed_activity_statement",
            "detailed.activity.statement.wizard",
        )

    def test_04_el_modulo_es_inerte_sin_agrupar(self):
        """Sin agrupamiento el wizard no toca la seleccion original."""
        wiz = (
            self.env["outstanding.statement.wizard"]
            .with_context(active_ids=self.empresa.ids, model="res.partner")
            .create({"date_end": self.date_end, "forum_group_address": "none"})
        )
        data = wiz._prepare_statement()
        self.assertEqual(list(data["partner_ids"]), self.empresa.ids)
        self.assertNotIn("forum_group_address", data)

    def test_05_cada_factura_cae_en_su_sucursal(self):
        res = self._reporte(
            "report.partner_statement.outstanding_statement",
            "outstanding.statement.wizard",
            "invoice",
        )
        refs = {
            pid: {ln["move_id"] for cur in d["currencies"].values() for ln in cur["lines"]}
            for pid, d in res["data"].items()
        }
        self.assertIn(self.inv_a1.name, refs.get(self.suc_a.id, set()))
        self.assertIn(self.inv_b1.name, refs.get(self.suc_b.id, set()))
        self.assertIn(self.inv_emp.name, refs.get(self.empresa.id, set()))
        self.assertNotIn(self.inv_b1.name, refs.get(self.suc_a.id, set()))

    def test_06_entrega_usa_el_deposito(self):
        res = self._reporte(
            "report.partner_statement.outstanding_statement",
            "outstanding.statement.wizard",
            "delivery",
        )
        refs = {
            pid: {ln["move_id"] for cur in d["currencies"].values() for ln in cur["lines"]}
            for pid, d in res["data"].items()
        }
        self.assertIn(self.inv_a1.name, refs.get(self.entrega_a.id, set()))
        self.assertIn(self.inv_b1.name, refs.get(self.entrega_b.id, set()))
        self.assertNotIn(self.inv_a1.name, refs.get(self.suc_a.id, set()))

    def test_07_pago_a_cuenta_sigue_la_direccion_atribuida(self):
        """Un pago a cuenta registrado desde una factura queda en esa sucursal."""
        pago = self.env["account.payment"].create(
            {
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": self.empresa.id,
                "amount": 90.0,
                "date": fields.Date.from_string("2026-08-01"),
                "forum_address_partner_id": self.suc_b.id,
                "forum_shipping_partner_id": self.entrega_b.id,
            }
        )
        pago.action_post()
        for modo, esperado in (("invoice", self.suc_b), ("delivery", self.entrega_b)):
            res = self._reporte(
                "report.partner_statement.outstanding_statement",
                "outstanding.statement.wizard",
                modo,
            )
            refs = {
                pid: {
                    ln["move_id"]
                    for cur in d["currencies"].values()
                    for ln in cur["lines"]
                }
                for pid, d in res["data"].items()
            }
            self.assertIn(
                pago.move_id.name,
                refs.get(esperado.id, set()),
                f"El pago a cuenta no quedo en {esperado.name} (modo {modo})",
            )
        # Y la suma sigue cuadrando con el nativo.
        self._comparar(
            "report.partner_statement.outstanding_statement",
            "outstanding.statement.wizard",
        )

    def test_08_pago_cruzado_sigue_a_la_factura(self):
        """Un pago atribuido a B que cancela una factura de A se ve bajo A."""
        wiz = (
            self.env["account.payment.register"]
            .with_context(
                active_model="account.move", active_ids=self.inv_a2.ids
            )
            .create({"amount": 250.0, "payment_date": "2026-09-01"})
        )
        pagos = wiz._create_payments()
        # El wizard atribuye el pago a la direccion de la factura que cancela.
        self.assertEqual(pagos.move_id.forum_address_partner_id, self.suc_a)
        self.assertTrue(self.inv_a2.payment_state in ("paid", "in_payment"))
        # La factura cancelada desaparece del pendiente de A, y nada aparece en B.
        res = self._reporte(
            "report.partner_statement.outstanding_statement",
            "outstanding.statement.wizard",
            "invoice",
        )
        refs = {
            pid: {ln["move_id"] for cur in d["currencies"].values() for ln in cur["lines"]}
            for pid, d in res["data"].items()
        }
        self.assertNotIn(self.inv_a2.name, refs.get(self.suc_a.id, set()))
        self.assertNotIn(pagos.move_id.name, refs.get(self.suc_b.id, set()))
        self._comparar(
            "report.partner_statement.outstanding_statement",
            "outstanding.statement.wizard",
        )

    def test_09_compone_el_sql_en_vez_de_pisarlo(self):
        """Sin agrupar no toca el SQL; agrupando solo cambia la clave de grupo.

        Es la prueba de no-regresion que importa en FORUM, donde
        `fix_partner_statement` (LocalizacionUy) reescribe estas mismas
        consultas para excluir las diferencias de cambio. Si este modulo
        copiara el SQL de OCA en vez de componer sobre el, esos filtros
        desapareceran sin que nadie se entere.
        """
        rep = self.env["report.partner_statement.outstanding_statement"]
        args = ((self.empresa.id,), self.date_end, "asset_receivable")
        base = rep._display_outstanding_lines_sql_q1(*args)
        self.assertNotIn(
            "forum_address_partner_id", base, "sin agrupar no se debe tocar el SQL"
        )
        dirs = self.env["res.partner"].search([("id", "child_of", self.empresa.ids)])
        agrupado = rep.with_context(
            forum_group_address="invoice", forum_address_ids=tuple(dirs.ids)
        )._display_outstanding_lines_sql_q1(*args)
        self.assertIn("forum_address_partner_id", agrupado)
        # El WHERE no se toca nunca: es lo que garantiza que no se pierdan lineas.
        self.assertIn("l.partner_id IN", agrupado)
        # Y deshaciendo la sustitucion se tiene que recuperar el SQL base
        # exacto: ni un filtro de mas, ni uno de menos.
        expr = rep.with_context(
            forum_group_address="invoice", forum_address_ids=tuple(dirs.ids)
        )._forum_partner_expr()
        rehecho = agrupado.replace(f"{expr} AS partner_id", "l.partner_id").replace(
            expr, "l.partner_id"
        )
        self.assertEqual(
            rehecho, base, "el agrupamiento cambio algo mas que la clave de grupo"
        )

    def test_10_saldo_por_factura_coincide_con_odoo(self):
        """El pendiente de cada factura es el amount_residual de Odoo."""
        res = self._reporte(
            "report.partner_statement.outstanding_statement",
            "outstanding.statement.wizard",
            "invoice",
        )
        del_reporte = {}
        for d in res["data"].values():
            for cur in d["currencies"].values():
                for ln in cur["lines"]:
                    del_reporte[ln["move_id"]] = (
                        del_reporte.get(ln["move_id"], 0.0) + ln["open_amount"]
                    )
        muestra = (self.inv_a1, self.inv_b1, self.inv_emp)
        for mv in muestra:
            self.assertAlmostEqual(
                del_reporte.get(mv.name, 0.0),
                mv.amount_residual,
                places=2,
                msg=f"{mv.name}: el reporte no coincide con amount_residual",
            )

    def test_11_sql_roto_corta_en_vez_de_mentir(self):
        """Si el SQL base cambia de forma, se corta con un error explicito."""
        from odoo.exceptions import UserError

        rep = self.env["report.partner_statement.outstanding_statement"].with_context(
            forum_group_address="invoice", forum_address_ids=(self.empresa.id,)
        )
        with self.assertRaises(UserError):
            rep._forum_reescribir_sql(
                "SELECT l.partner_id FROM otra_tabla x", "prueba"
            )
