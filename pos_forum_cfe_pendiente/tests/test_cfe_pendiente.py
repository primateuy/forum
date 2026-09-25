# -*- coding: utf-8 -*-
"""
Un fallo de emisión del CFE no puede perder la venta ni trancar el PDV.

Lo que se fija acá:
  1. si la emisión falla, la venta queda guardada y la factura en BORRADOR,
  2. la orden queda marcada con el motivo,
  3. el cierre de caja queda bloqueado mientras haya pendientes,
  4. el reintento postea esa misma factura y limpia la marca.
"""

from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "forum_cfe_pendiente")
class TestCfeEmisionPendiente(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Una caja que no tenga sesión abierta: Odoo no deja abrir dos.
        con_sesion = cls.env["pos.session"].search([("state", "!=", "closed")]).config_id
        cls.config = cls.env["pos.config"].search([
            ("company_id", "=", cls.env.company.id),
            ("id", "not in", con_sesion.ids),
            ("payment_method_ids", "!=", False),
        ], limit=1)
        if not cls.config:
            cls.skipTest(cls, "No hay ninguna caja libre en esta base.")
        cls.config.write({"auto_check_invoice": True})
        cls.partner = cls.env["res.partner"].search([("customer_rank", ">", 0)], limit=1) \
            or cls.env["res.partner"].create({"name": "Cliente de prueba CFE"})
        cls.producto = cls.env["product.product"].search(
            [("available_in_pos", "=", True), ("type", "!=", "service")], limit=1)
        if not cls.producto:
            cls.skipTest(cls, "No hay productos de PDV en esta base.")

    def _abrir_sesion(self):
        sesion = self.env["pos.session"].create({
            "config_id": self.config.id,
            "user_id": self.env.uid,
        })
        sesion.action_pos_session_open()
        return sesion

    def _crear_orden(self, sesion):
        precio = self.producto.lst_price or 100.0
        metodo = sesion.config_id.payment_method_ids.filtered(lambda m: m.is_cash_count)[:1] \
            or sesion.config_id.payment_method_ids[:1]
        orden = self.env["pos.order"].create({
            "session_id": sesion.id,
            "company_id": sesion.company_id.id,
            "partner_id": self.partner.id,
            "amount_tax": 0.0,
            "amount_total": precio,
            "amount_paid": precio,
            "amount_return": 0.0,
            "to_invoice": True,
            "lines": [(0, 0, {
                "product_id": self.producto.id,
                "qty": 1,
                "price_unit": precio,
                "price_subtotal": precio,
                "price_subtotal_incl": precio,
            })],
        })
        orden.add_payment({
            "amount": precio,
            "payment_date": fields.Date.today(),
            "payment_method_id": metodo.id,
            "pos_order_id": orden.id,
        })
        orden.action_pos_order_paid()
        return orden

    def test_emision_fallida_deja_la_venta_y_la_factura_en_borrador(self):
        sesion = self._abrir_sesion()
        orden = self._crear_orden(sesion)

        # Se interviene el punto exacto donde se emite, para que el resto del
        # posteo corra de verdad y no haya que salir a la red.
        Move = type(self.env["account.move"])

        def _emision_que_falla(self):
            raise UserError("Facturación electrónica: receptor no configurado")

        with patch.object(Move, "genera_xml_y_firma_factura", _emision_que_falla, create=True):
            orden._generate_pos_order_invoice()

        self.assertTrue(orden.exists(), "La venta se perdió: tiene que quedar guardada.")
        self.assertTrue(orden.account_move, "Tiene que quedar la factura creada.")
        self.assertEqual(orden.account_move.state, "draft", "La factura tiene que quedar en borrador.")
        self.assertTrue(orden.cfe_emision_pendiente, "La orden tiene que quedar marcada como pendiente.")
        self.assertIn("receptor", orden.cfe_emision_error or "",
                      "Tiene que guardarse el motivo para mostrárselo al cajero.")
        self.assertEqual(orden.cfe_emision_intentos, 1)

        # Con una emisión pendiente no se puede cerrar la caja.
        bloqueo = sesion._cannot_close_session()
        self.assertTrue(bloqueo and bloqueo.get("successful") is False,
                        "El cierre de caja tiene que quedar bloqueado.")
        self.assertIn(orden.pos_reference or orden.name, bloqueo["message"])

        # El reintento postea esa misma factura, sin rehacer nada. Ahora la
        # emisión "funciona": no sale a la red, sólo deja seguir el posteo.
        move_id = orden.account_move.id
        with patch.object(Move, "genera_xml_y_firma_factura", lambda self: True, create=True):
            resultado = self.env["pos.order"].reintentar_emision_cfe(orden.id)
        self.assertTrue(resultado["ok"], "El reintento tenía que funcionar: %s" % resultado.get("error"))
        self.assertEqual(orden.account_move.id, move_id, "Se posteó otra factura en vez de la que estaba.")
        self.assertEqual(orden.account_move.state, "posted")
        self.assertFalse(orden.cfe_emision_pendiente)
        self.assertFalse(orden.cfe_emision_error)

    def test_el_pdv_recibe_el_estado_de_emision(self):
        """Lo que create_from_ui le devuelve al PDV lleva el estado de emisión."""
        sesion = self._abrir_sesion()
        orden = self._crear_orden(sesion)
        orden.write({"cfe_emision_pendiente": True, "cfe_emision_error": "motivo de prueba"})

        res = self.env["pos.order"]._cfe_agregar_estado_emision([{
            "id": orden.id,
            "pos_reference": orden.pos_reference,
            "account_move": False,
        }])

        self.assertTrue(res[0]["cfe_emision_pendiente"],
                        "El PDV no se entera de que la emisión quedó pendiente.")
        self.assertEqual(res[0]["cfe_emision_error"], "motivo de prueba")
        # Y una venta sin problemas viaja en falso.
        orden._cfe_marcar_resuelto()
        res = self.env["pos.order"]._cfe_agregar_estado_emision([{"id": orden.id}])
        self.assertFalse(res[0]["cfe_emision_pendiente"])
