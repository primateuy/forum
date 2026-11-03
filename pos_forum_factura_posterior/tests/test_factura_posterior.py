# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo import fields
from odoo.addons.point_of_sale.tests.common import TestPoSCommon
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestFacturaPosterior(TestPoSCommon):
    """
    Facturación de una venta del PDV después de cerrada la caja.

    Lo que se verifica no es que el core sepa facturar —ya lo sabe— sino las
    dos fechas que este módulo corrige y que la reversión del cierre siga
    quedando conciliada.
    """

    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.producto = self.create_product("Producto factura posterior", self.categ_basic, 100.0, 50.0)
        self.cliente = self.env["res.partner"].create({"name": "Cliente que pide la factura después"})

    def _vender_y_cerrar_caja(self, dias_atras=5):
        """
        Deja una venta cobrada y sin facturar en una sesión ya cerrada.

        :param int dias_atras: antigüedad de la venta, para que la fecha de la
            orden y la de hoy no puedan coincidir por casualidad.
        :return pos.order: la venta.
        """
        self.open_new_session()
        orden = self.env["pos.order"].browse(
            self.env["pos.order"].create_from_ui([
                self.create_ui_order_data([(self.producto, 1)], uid="venta-sin-factura")
            ])[0]["id"]
        )
        # La fecha de la venta se retrasa a mano: create_from_ui la pisa con la
        # del momento y lo que se está probando es justamente que la factura la
        # respete.
        fecha_venta = fields.Datetime.now() - timedelta(days=dias_atras)
        orden.write({"date_order": fecha_venta})
        self.pos_session.action_pos_session_closing_control()
        self.assertEqual(self.pos_session.state, "closed")
        self.assertEqual(orden.state, "done", "Sin facturar, el cierre la deja en 'done'.")
        return orden

    def test_factura_posterior_usa_la_fecha_de_la_venta(self):
        """La factura sale con la fecha de la orden, no con la de hoy."""
        orden = self._vender_y_cerrar_caja()
        orden.write({"partner_id": self.cliente.id})

        orden.action_pos_order_invoice()

        factura = orden.account_move
        self.assertTrue(factura, "Tiene que haberse creado la factura.")
        self.assertEqual(orden.state, "invoiced")
        self.assertEqual(
            factura.invoice_date,
            fields.Date.context_today(orden, orden.date_order),
            "La fecha de emisión tiene que ser la de la venta, no la de hoy.",
        )
        self.assertEqual(
            factura.date, factura.invoice_date,
            "Sin período bloqueado, la fecha contable sigue a la de emisión.",
        )

    def test_la_reversion_del_cierre_queda_en_la_fecha_de_la_venta(self):
        """
        La reversión del asiento de cierre acompaña a la factura.

        Si quedara en la fecha de hoy, el ingreso de esta venta aparecería dos
        veces en el período del cierre y en negativo en el de hoy.
        """
        orden = self._vender_y_cerrar_caja()
        orden.write({"partner_id": self.cliente.id})
        fecha_venta = fields.Date.context_today(orden, orden.date_order)

        orden.action_pos_order_invoice()

        # Los asientos de pago del PDV van al mismo diario y su ref también
        # lleva el nombre de la orden; se los descarta por pos_payment_ids.
        reversion = self.env["account.move"].search([
            ("journal_id", "=", orden.config_id.journal_id.id),
            ("ref", "like", "%%%s%%" % orden.name),
            ("pos_payment_ids", "=", False),
        ])
        self.assertTrue(reversion, "El core tiene que haber creado la reversión del cierre.")
        self.assertEqual(
            reversion.date, fecha_venta,
            "La reversión tiene que quedar en el mismo período que la factura.",
        )
        self.assertEqual(reversion.state, "posted")

    def test_la_venta_facturada_en_caja_abierta_no_cambia(self):
        """Con la sesión abierta sigue mandando el comportamiento del core."""
        self.open_new_session()
        orden = self.env["pos.order"].browse(
            self.env["pos.order"].create_from_ui([
                self.create_ui_order_data(
                    [(self.producto, 1)], customer=self.cliente, is_invoiced=True, uid="venta-facturada"
                )
            ])[0]["id"]
        )
        self.assertEqual(orden.state, "invoiced")
        self.assertEqual(
            orden.account_move.invoice_date,
            fields.Date.context_today(orden, orden.date_order),
            "Con la caja abierta el core ya usaba la fecha de la orden.",
        )

    def test_sin_cliente_no_factura(self):
        """Sin cliente la venta no se puede facturar, con un mensaje entendible."""
        from odoo.exceptions import UserError

        orden = self._vender_y_cerrar_caja()
        self.assertFalse(orden.partner_id)
        with self.assertRaises(UserError):
            orden.action_pos_order_invoice()
