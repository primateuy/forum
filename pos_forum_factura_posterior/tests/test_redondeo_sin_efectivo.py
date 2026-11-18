# -*- coding: utf-8 -*-

from odoo.addons.point_of_sale.tests.common import TestPoSCommon
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestRedondeoSinEfectivo(TestPoSCommon):
    """
    Venta con tarjeta con centavos de diferencia, en una caja que redondea sólo el efectivo.

    Caso real (producción, 18-11-2026): promoción OCA del 20 % con el descuento
    truncado en el pinpad, 4.798,40 de total contra 4.798,39 cobrados. El core
    agregaba la línea de redondeo sin cuenta y la factura no se podía guardar
    (``account_move_line_check_accountable_required_fields``).
    """

    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.redondeo = self.env["account.cash.rounding"].create({
            "name": "Redondeo al peso (test)",
            "rounding": 1.0,
            "strategy": "add_invoice_line",
            "rounding_method": "HALF-UP",
            "profit_account_id": self.company_data["default_account_revenue"].id,
            "loss_account_id": self.company_data["default_account_expense"].id,
        })
        self.config.write({
            "cash_rounding": True,
            "only_round_cash_method": True,
            "rounding_method": self.redondeo.id,
        })
        self.producto = self.create_product("Producto promo OCA", self.categ_basic, 100.40, 50.0)
        self.cliente = self.env["res.partner"].create({"name": "Cliente con promo OCA"})

    def _venta_con_tarjeta(self, cobrado, uid):
        """Venta de 100,40 cobrada con tarjeta y después alineada a lo que cobró el pinpad.

        Es lo que hace ``odoo_pos_oca_promociones``: el PDV manda el importe entero y el
        servidor lo baja al de la transacción.
        """
        orden = self.env["pos.order"].browse(
            self.env["pos.order"].create_from_ui([
                self.create_ui_order_data(
                    [(self.producto, 1)], payments=[(self.bank_pm1, 100.40)], uid=uid)
            ])[0]["id"]
        )
        orden.payment_ids.write({"amount": cobrado})
        orden._compute_batch_amount_all()
        return orden

    def test_factura_posterior_con_un_centavo_menos(self):
        self.open_new_session()
        orden = self._venta_con_tarjeta(100.39, "promo-centavo")
        self.assertAlmostEqual(orden.amount_paid, 100.39)
        self.pos_session.action_pos_session_closing_control()
        self.assertEqual(orden.state, "done")
        orden.write({"partner_id": self.cliente.id})

        orden.action_pos_order_invoice()

        factura = orden.account_move
        self.assertTrue(factura, "La venta quedó facturada.")
        self.assertEqual(factura.state, "posted")
        self.assertAlmostEqual(factura.amount_total, 100.39,
                               msg="La factura es por lo que se cobró, no por el total de la orden.")
        linea = factura.line_ids.filtered(lambda l: l.display_type == "rounding")
        self.assertEqual(len(linea), 1)
        self.assertEqual(linea.account_id, self.redondeo.profit_account_id,
                         "La línea de redondeo lleva la cuenta del método de la caja.")
        self.assertAlmostEqual(abs(linea.balance), 0.01)
        reversion = self.env["account.move"].search([
            ("ref", "ilike", orden.name), ("journal_id", "=", self.config.journal_id.id),
            ("move_type", "=", "entry"), ("id", "!=", self.pos_session.move_id.id)]).filtered(
            lambda m: "closing entry" in (m.ref or "").lower() or "cierre" in (m.ref or "").lower())
        self.assertEqual(len(reversion), 1, "La reversión del cierre se creó.")
        self.assertEqual(reversion.state, "posted")
        self.assertAlmostEqual(
            sum(reversion.line_ids.mapped("debit")), sum(reversion.line_ids.mapped("credit")),
            msg="La reversión cuadra con el centavo de redondeo.")
        self.assertTrue(reversion.line_ids.filtered(lambda l: l.display_type == "rounding"))

    def test_una_diferencia_de_un_peso_o_mas_no_es_redondeo(self):
        """Lo del caso D (un pago mal ligado, 1.395 de menos) no se esconde en un redondeo."""
        self.open_new_session()
        orden = self._venta_con_tarjeta(99.00, "pago-de-menos")
        self.assertFalse(orden._forum_redondeo_sin_efectivo())

    def test_sin_diferencia_no_se_toca(self):
        self.open_new_session()
        orden = self._venta_con_tarjeta(100.40, "sin-diferencia")
        self.assertFalse(orden._forum_redondeo_sin_efectivo())
        self.assertFalse(orden._prepare_invoice_vals()["invoice_cash_rounding_id"])

    def test_caja_sin_redondeo_no_se_toca(self):
        self.config.write({"cash_rounding": False})
        self.open_new_session()
        orden = self._venta_con_tarjeta(100.39, "caja-sin-redondeo")
        self.assertFalse(orden._forum_redondeo_sin_efectivo())
