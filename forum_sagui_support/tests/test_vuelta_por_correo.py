# -*- coding: utf-8 -*-
# Riesgo 2: el visitante cierra el chat antes de que el responsable conteste.
#
# LA TRAMPA QUE ESTO CAZA, y que un test de "¿existe el canal?" no caza nunca: cerrar una sesión de
# livechat NO BORRA EL CANAL. `_close_livechat_session` sólo pone `livechat_active = False`
# (`im_livechat/models/discuss_channel.py:120`). El canal sigue ahí, `_canal_de` lo encuentra, el
# `message_post` funciona, no hay excepción, no hay warning — y el visitante no ve nada porque
# cerró la pestaña. La consulta se pierde en silencio, que es la peor forma de perderla.
#
# Por eso acá se prueba el efecto y no la llamada: que salga el `mail.mail`, a quién, con qué
# asunto y con la respuesta adentro.
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

PREGUNTA = "Necesito saber cómo anulo un comprobante que ya le mandé a la DGI por error"
RESPUESTA = "<p>Se anula con una <b>nota de crédito</b> por el total.</p>"


@tagged("post_install", "-at_install", "forum_sagui")
class TestVueltaPorCorreo(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bot = cls.env.ref("forum_sagui_support.partner_sagui_soporte")
        cls.paso_consulta = cls.env.ref("forum_sagui_support.step_sagui_consulta")
        Param = cls.env["ir.config_parameter"].sudo()
        Param.set_param("forum_sagui_support.url", "http://sagui.test")
        Param.set_param("forum_sagui_support.token", "tok")
        Param.set_param("forum_sagui_support.cursor", "0")
        cls.operador = cls.env["res.users"].create(
            {"name": "Vicky Correo", "login": "vicky_correo_test"})
        # El visitante NO es el bot. Parece obvio y es justo lo que el defecto del asunto no
        # distinguía: si en el test habla todo el mismo autor, el filtro por autor no se prueba.
        cls.visitante = cls.env["res.partner"].create({"name": "Visitante de prueba"})
        cls.relay = cls.env["sagui.relay"]

    def _canal(self, correo="visitante@ejemplo.com", activo=True):
        canal = self.env["discuss.channel"].sudo().create({
            "name": "Visitante de prueba", "channel_type": "livechat",
            "anonymous_name": "Visitante de prueba",
            "livechat_operator_id": self.operador.partner_id.id,
            "livechat_active": activo,
            "channel_member_ids": [(0, 0, {"partner_id": self.bot.id}),
                                   (0, 0, {"partner_id": self.operador.partner_id.id})],
        })
        if correo:
            canal.sudo().message_post(body=correo, message_type="comment",
                                      subtype_xmlid="mail.mt_comment",
                                      author_id=self.visitante.id)
        canal.sudo().message_post(body=PREGUNTA, message_type="comment",
                                  subtype_xmlid="mail.mt_comment", author_id=self.visitante.id)
        return canal

    def _cola(self, canal, cuerpo=RESPUESTA, seq=9001, quien="Vicky Correo"):
        """La respuesta del responsable, como la devuelve /outbox."""
        return {"messages": [{"seq": seq, "conversation_ref": "forum:livechat:%s" % canal.uuid,
                              "kind": "escalation_answer", "body": cuerpo,
                              "assigned_to": quien}],
                "cursor": seq}

    def _traer(self, respuesta):
        with patch.object(type(self.relay), "_post", lambda *a, **k: respuesta), \
             patch.object(type(self.relay), "_confirmar_al_commitear", lambda *a, **k: None):
            return self.relay.traer_respuestas()

    def _correos_a(self, direccion):
        return self.env["mail.mail"].sudo().search([("email_to", "=", direccion)])

    # ============ la sesión muerta se detecta ============
    def test_una_sesion_cerrada_NO_es_un_canal_vivo(self):
        """El canal existe igual. Si se mira sólo la existencia, esto pasa desapercibido."""
        canal = self._canal(activo=False)
        self.assertTrue(canal.exists(), "cerrar la sesión no borra el canal: ésa es la trampa")
        self.assertTrue(self.relay._canal_de("forum:livechat:%s" % canal.uuid),
                        "y `_canal_de` lo encuentra perfecto")
        self.assertTrue(self.relay._sesion_muerta(canal))

    def test_un_DM_nunca_se_considera_muerto(self):
        """Un DM queda en la bandeja: el usuario lo ve cuando vuelve. No se le manda correo."""
        dm = self.env["discuss.channel"].sudo().create(
            {"name": "dm", "channel_type": "chat"})
        self.assertFalse(self.relay._sesion_muerta(dm))

    def test_una_sesion_abierta_no_dispara_el_correo(self):
        canal = self._canal(activo=True)
        self._traer(self._cola(canal))
        self.assertFalse(self._correos_a("visitante@ejemplo.com"),
                         "con la sesión viva la respuesta va al chat, no por correo")
        self.assertIn("nota de crédito", canal.message_ids[0].body)

    # ============ con correo: llega ============
    def test_con_la_sesion_muerta_la_respuesta_SALE_POR_CORREO(self):
        canal = self._canal(correo="visitante@ejemplo.com", activo=False)
        self._traer(self._cola(canal))
        correos = self._correos_a("visitante@ejemplo.com")
        self.assertEqual(len(correos), 1, "la promesa del guion era ésta y no se cumplió")
        self.assertIn("nota de crédito", correos.body_html)
        self.assertIn("<b>nota de crédito</b>", correos.body_html,
                      "el cuerpo viajó con el HTML escapado")
        self.assertNotIn("&lt;b&gt;", correos.body_html)

    def test_el_asunto_REFERENCIA_la_consulta(self):
        """«Respuesta de soporte» a secas, días después y en una bandeja llena, no se abre."""
        canal = self._canal(correo="visitante@ejemplo.com", activo=False)
        self._traer(self._cola(canal))
        asunto = self._correos_a("visitante@ejemplo.com").subject
        self.assertIn("anulo un comprobante", asunto,
                      "el asunto tiene que dejar reconocer de qué consulta se trata: %r" % asunto)

    def test_el_asunto_NO_agarra_el_saludo_DEL_BOT(self):
        """Encontrado EN VIVO el 12-sep-2026: salió «Tu consulta: ¡Hola! Soy Sagui…».

        El filtro era por largo y los pasos del guion son largos. Un visitante que escribe menos
        que el saludo del bot —o sea, casi cualquiera— se llevaba el saludo como asunto.
        """
        canal = self._canal(correo="visitante@ejemplo.com", activo=False)
        # El bot habla primero y habla largo, igual que el guion de verdad.
        canal.sudo().message_post(
            body="¡Hola! Soy Sagui. Respondo con la documentación del equipo y te digo en qué "
                 "documento me baso. Si algo no está documentado, te lo derivo.",
            message_type="comment", subtype_xmlid="mail.mt_comment", author_id=self.bot.id)
        self._traer(self._cola(canal))
        asunto = self._correos_a("visitante@ejemplo.com").subject
        self.assertNotIn("Soy Sagui", asunto,
                         "el asunto se llevó el saludo del bot en vez de la consulta: %r" % asunto)
        self.assertIn("anulo un comprobante", asunto)

    def test_el_correo_dice_quien_contesto(self):
        canal = self._canal(correo="visitante@ejemplo.com", activo=False)
        self._traer(self._cola(canal, quien="Vicky Correo"))
        self.assertIn("Vicky Correo", self._correos_a("visitante@ejemplo.com").body_html)

    def test_el_correo_sale_con_un_remitente_valido(self):
        """Sin `mail.alias.domain` Odoo arma un Return-Path con un `False` adentro y el envío muere
        con «Malformed 'Return-Path' or 'From' address». Pasa hoy en esta base."""
        canal = self._canal(correo="visitante@ejemplo.com", activo=False)
        self._traer(self._cola(canal))
        remitente = self._correos_a("visitante@ejemplo.com").email_from or ""
        self.assertTrue(remitente, "el correo salió sin remitente")
        self.assertNotIn("False", remitente)
        self.assertIn("@", remitente)

    def test_queda_constancia_en_el_canal_para_el_operador(self):
        canal = self._canal(correo="visitante@ejemplo.com", activo=False)
        self._traer(self._cola(canal))
        cuerpos = " ".join(canal.message_ids.mapped("body"))
        self.assertIn("por correo", cuerpos,
                      "el operador abre la sesión y tiene que ver en qué terminó")

    # ============ sin correo válido: no se pierde ============
    def test_sin_correo_la_respuesta_QUEDA_EN_EL_CANAL(self):
        canal = self._canal(correo="", activo=False)
        self._traer(self._cola(canal))
        self.assertFalse(self.env["mail.mail"].sudo().search([("subject", "like", "anulo")]),
                         "no había correo: no se puede haber mandado nada")
        self.assertIn("nota de crédito", " ".join(canal.message_ids.mapped("body")),
                      "sin correo la respuesta igual tiene que quedar, para el operador")

    def test_el_guion_AVISA_ANTES_de_que_pase(self):
        """El aviso previo es lo que hace honesto al caso sin correo: se avisó en el momento."""
        paso = self.env.ref("forum_sagui_support.step_sagui_correo")
        textos = [paso.message or ""]
        siguientes = paso.triggering_answer_ids.mapped("name") if paso.triggering_answer_ids else []
        todo = " ".join(textos + list(siguientes)).lower()
        self.assertTrue(
            any(p in todo for p in ("correo", "mail", "escribir", "responder")),
            "el paso que pide el correo tiene que decir para qué se pide: %r" % todo[:200])

    def test_lo_que_no_tiene_ni_canal_ni_correo_se_loguea_y_no_rompe(self):
        antes = self.env["mail.mail"].sudo().search_count([])
        entregados = self.relay._sin_hilo(
            {"conversation_ref": "forum:livechat:no-existe", "body": RESPUESTA}, canal=None)
        self.assertFalse(entregados)
        self.assertEqual(self.env["mail.mail"].sudo().search_count([]), antes)

    # ============ dedup: el correo tampoco se manda dos veces ============
    def test_el_mismo_seq_no_manda_dos_correos(self):
        canal = self._canal(correo="visitante@ejemplo.com", activo=False)
        cola = self._cola(canal, seq=9002)
        self._traer(cola)
        self.env["ir.config_parameter"].sudo().set_param("forum_sagui_support.cursor", "0")
        self._traer(cola)
        self.assertEqual(len(self._correos_a("visitante@ejemplo.com")), 1,
                         "la dedup por seq tiene que cubrir también la salida por correo")
