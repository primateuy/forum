# Copyright 2026 Primate (https://primate.uy)
"""Pruebas de la cola de registro de facturas.

Lo que importa verificar es que la cola no cambie el resultado contable: las
mismas facturas que hoy se registran a mano tienen que terminar registradas
igual, solo que mas tarde y de a tandas. Y que un problema en una factura no se
lleve puestas a las demas.
"""

from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPostQueue(TransactionCase):
    """Se arma sobre el plan de cuentas real de la base, no sobre el de
    `AccountTestInvoicingCommon`: esa clase reconfigura la moneda de la compania
    y falla en cuanto hay apuntes contables. El diario se crea aca, sin punto de
    emision, para no disparar la factura electronica ni el tope de lineas."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company
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
        # Se reutiliza lo que ya exista en la base en vez de crearlo siempre:
        # el codigo de diario es unico por compania, asi que una corrida previa
        # que haya dejado el diario creado haria fallar el arranque.
        cls.diario = cls.env["account.journal"].search(
            [("code", "=", "TSTCO"), ("company_id", "=", cls.company.id)], limit=1
        ) or cls.env["account.journal"].create(
            {
                "name": "Ventas prueba cola",
                "code": "TSTCO",
                "type": "sale",
                "company_id": cls.company.id,
                "default_account_id": cls.cuenta_ingreso.id,
            }
        )
        if "diario_cfe" in cls.env["account.journal"]._fields:
            cls.diario.diario_cfe = False
        cls.producto = cls.env["product.product"].search(
            [("name", "=", "Servicio demo cola")], limit=1
        ) or cls.env["product.product"].create(
            {"name": "Servicio demo cola", "type": "service"}
        )
        cls.cliente = cls.env["res.partner"].search(
            [("name", "=", "CLIENTE DEMO COLA S.A.")], limit=1
        ) or cls.env["res.partner"].create(
            {
                "name": "CLIENTE DEMO COLA S.A.",
                "property_account_receivable_id": cls.cuenta_cobrar.id,
            }
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "forum.post_queue_min_moves", "2"
        )

    # === Utilidades =======================================================

    def _factura(self, lineas=1, fecha=None):
        fecha = fecha or fields.Date.today()
        return self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.cliente.id,
                "journal_id": self.diario.id,
                "invoice_date": fecha,
                "date": fecha,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.producto.id,
                            "quantity": 1,
                            "price_unit": 100.0,
                            "account_id": self.cuenta_ingreso.id,
                        }
                    )
                    for _ in range(lineas)
                ],
            }
        )

    def _registrar(self, moves, force_post=False):
        """Corre el asistente de registro como lo corre el usuario desde la lista."""
        wizard = (
            self.env["validate.account.move"]
            .with_context(active_model="account.move", active_ids=moves.ids)
            .create({"force_post": force_post})
        )
        return wizard.validate_move()

    # === Pruebas ==========================================================

    def test_01_una_sola_se_registra_en_el_momento(self):
        """Por debajo del minimo el comportamiento no cambia: se postea ya."""
        factura = self._factura()
        self._registrar(factura)
        self.assertEqual(factura.state, "posted")
        self.assertFalse(factura.forum_post_queue_state)

    def test_02_varias_quedan_en_cola(self):
        """Arriba del minimo no se postea nada todavia: solo se marca la cola."""
        facturas = self._factura() | self._factura() | self._factura()
        accion = self._registrar(facturas)

        self.assertEqual(set(facturas.mapped("state")), {"draft"})
        self.assertEqual(set(facturas.mapped("forum_post_queue_state")), {"queued"})
        self.assertEqual(accion.get("tag"), "display_notification")
        self.assertEqual(facturas.mapped("forum_post_queue_uid"), self.env.user)

    def test_03_el_cron_registra_la_cola(self):
        """El cron deja todo registrado y sin marca de cola."""
        facturas = self._factura() | self._factura() | self._factura()
        self._registrar(facturas)

        self.env["account.move"]._forum_cron_post_queued()

        self.assertEqual(set(facturas.mapped("state")), {"posted"})
        self.assertFalse(any(facturas.mapped("forum_post_queue_state")))

    def test_04_confirmar_a_mano_saca_de_la_cola(self):
        """Quien no quiere esperar entra a la factura y la confirma: sale de la cola."""
        facturas = self._factura() | self._factura()
        self._registrar(facturas)
        elegida = facturas[0]

        elegida.action_post()

        self.assertEqual(elegida.state, "posted")
        self.assertFalse(elegida.forum_post_queue_state)
        self.assertEqual(facturas[1].forum_post_queue_state, "queued")

    def test_05_las_tandas_respetan_el_tope(self):
        """Ninguna tanda supera el tope, y ninguna factura se parte en dos."""
        facturas = self._factura(lineas=3) | self._factura(lineas=3) | self._factura(lineas=3)
        self._registrar(facturas)

        tandas = self.env["account.move"]._forum_armar_tandas(facturas, 6)

        self.assertEqual([len(t) for t, _n in tandas], [2, 1])
        self.assertTrue(all(lineas <= 6 for _t, lineas in tandas))
        repartidas = self.env["account.move"].browse()
        for tanda, _lineas in tandas:
            repartidas |= tanda
        self.assertEqual(repartidas, facturas)

    def test_06_una_factura_con_error_no_frena_a_las_demas(self):
        """La que falla queda marcada con el motivo; el resto se registra igual."""
        buenas = self._factura() | self._factura()
        mala = self._factura()
        facturas = buenas | mala
        self._registrar(facturas)

        original = type(self.env["account.move"])._forum_post_moves

        def falla_en_la_mala(self_model, moves):
            if mala.id in moves.ids:
                raise ValueError("fallo simulado de la prueba")
            return original(self_model, moves)

        with patch.object(
            type(self.env["account.move"]), "_forum_post_moves", falla_en_la_mala
        ):
            # Tope de 1 linea por tanda no alcanza para aislarla: el reintento de
            # a una es el camino que tiene que marcarla sin voltear al resto.
            self.env["account.move"]._forum_cron_post_queued()

        self.assertEqual(set(buenas.mapped("state")), {"posted"})
        self.assertEqual(mala.state, "draft")
        self.assertEqual(mala.forum_post_queue_state, "error")
        self.assertIn("fallo simulado", mala.forum_post_queue_error)

    def test_07_cancelar_saca_de_la_cola(self):
        """Una factura cancelada no puede quedar esperando que el cron la registre."""
        facturas = self._factura() | self._factura()
        self._registrar(facturas)

        facturas[0].button_cancel()

        self.assertEqual(facturas[0].state, "cancel")
        self.assertFalse(facturas[0].forum_post_queue_state)

    def test_08_fecha_futura_sale_de_la_cola(self):
        """Sin forzar, Odoo deja las futuras para su fecha: no pueden quedar en cola.

        Si quedaran marcadas, el cron las volveria a tomar cada 10 minutos para
        siempre sin poder registrarlas nunca.
        """
        futura = self._factura(fecha=fields.Date.today() + timedelta(days=30))
        hoy = self._factura()
        self._registrar(futura | hoy)

        self.env["account.move"]._forum_cron_post_queued()

        self.assertEqual(hoy.state, "posted")
        self.assertEqual(futura.state, "draft")
        self.assertFalse(futura.forum_post_queue_state)
        self.assertEqual(futura.auto_post, "at_date")

    def test_09_reintentar_vuelve_a_encolar(self):
        """El boton Reintentar de la factura con error la devuelve a la cola."""
        factura = self._factura()
        factura.write({"forum_post_queue_state": "error", "forum_post_queue_error": "x"})

        factura.action_forum_requeue()

        self.assertEqual(factura.forum_post_queue_state, "queued")
        self.assertFalse(factura.forum_post_queue_error)

    def test_10_quitar_de_la_cola(self):
        """Quitar de la cola deja la factura en borrador y sin marca."""
        facturas = self._factura() | self._factura()
        self._registrar(facturas)

        facturas.action_forum_dequeue()

        self.assertFalse(any(facturas.mapped("forum_post_queue_state")))
        self.assertEqual(set(facturas.mapped("state")), {"draft"})

    def test_11_encolar_no_recalcula_las_facturas(self):
        """Encolar no puede disparar el recalculo de las lineas dinamicas.

        Es la razon de ser de `_forum_write_cola`: sin saltear el recalculo,
        marcar la cola de un lote grande vuelve a dar el mismo RecursionError
        que impide registrarlo. Escribir de a poco no sirve como alternativa:
        el recalculo de cada factura cuesta casi lo mismo que registrarla.
        """
        capturado = {}
        original = type(self.env["account.move"]).write

        def espia(recordset, vals):
            if "forum_post_queue_state" in vals:
                capturado["skip"] = recordset.env.context.get("skip_invoice_sync")
            return original(recordset, vals)

        with patch.object(type(self.env["account.move"]), "write", espia):
            self._registrar(self._factura() | self._factura())

        self.assertTrue(
            capturado.get("skip"),
            "el encolado tiene que escribir con skip_invoice_sync activo",
        )
