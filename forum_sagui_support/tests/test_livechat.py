# -*- coding: utf-8 -*-
# La segunda entrada: el livechat del sitio. Lo que se prueba acá es el recorrido del visitante,
# que es distinto al del DM en tres cosas y en ninguna más: el hilo se identifica por `uuid` y no
# por id, el correo lo dio el guion y no el usuario de Odoo, y cuando Sagui deriva hay un pase
# nativo a un operador que en el DM no existe.
from unittest.mock import patch

from markupsafe import Markup

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "forum_sagui")
class TestLivechat(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bot = cls.env.ref("forum_sagui_support.partner_sagui_soporte")
        cls.guion = cls.env.ref("forum_sagui_support.chatbot_script_sagui")
        cls.paso_consulta = cls.env.ref("forum_sagui_support.step_sagui_consulta")
        cls.paso_operador = cls.env.ref("forum_sagui_support.step_sagui_operador")
        Param = cls.env["ir.config_parameter"].sudo()
        Param.set_param("forum_sagui_support.url", "http://sagui.test")
        Param.set_param("forum_sagui_support.token", "tok")
        cls.operador = cls.env["res.users"].create(
            {"name": "Vicky Operadora", "login": "vicky_livechat_test"})

    def _canal_livechat(self):
        """Una sesión de livechat como la que deja el widget del sitio."""
        return self.env["discuss.channel"].sudo().create({
            "name": "Visitante de prueba",
            "channel_type": "livechat",
            "anonymous_name": "Visitante de prueba",
            "livechat_operator_id": self.operador.partner_id.id,
            "livechat_active": True,
            "chatbot_current_step_id": self.paso_consulta.id,
            "channel_member_ids": [
                (0, 0, {"partner_id": self.bot.id}),
                (0, 0, {"partner_id": self.operador.partner_id.id}),
            ],
        })

    def _post(self, respuesta, registro=None):
        """Simula el borde HTTP con Sagui, con la forma que devuelve el endpoint."""
        def falso(self_, ruta, payload, timeout=None):
            if registro is not None:
                registro.append((ruta, payload))
            return respuesta
        return patch.object(type(self.env["sagui.relay"]), "_post", falso)

    # ================================================== el recorrido normal
    def test_una_consulta_del_visitante_se_responde_en_el_mismo_chat(self):
        canal = self._canal_livechat()
        visto = []
        with self._post({"status": "answered",
                         "body": "<p>Se anula con una <b>nota de crédito</b>.</p>"}, visto):
            siguiente = self.paso_consulta._process_answer(canal, "¿cómo anulo una factura?")

        self.assertEqual(len(visto), 1)
        ruta, payload = visto[0]
        self.assertEqual(ruta, "/sagui/support/ask")
        self.assertEqual(payload["conversation_ref"], "forum:livechat:%s" % canal.uuid,
                         "el livechat se identifica por uuid: el id no le sirve al visitante")
        self.assertEqual(payload["message"], "¿cómo anulo una factura?")

        ultimo = canal.message_ids[0]
        self.assertEqual(ultimo.author_id, self.bot)
        self.assertIn("<b>nota de crédito</b>", ultimo.body)
        self.assertNotIn("&lt;b&gt;", ultimo.body, "el HTML de Sagui no puede llegar escapado")
        self.assertEqual(siguiente, self.paso_consulta,
                         "el guion NO avanza: se queda conversando en este paso")

    def test_la_pregunta_le_llega_a_sagui_en_texto_plano(self):
        """`_process_answer` recibe el BODY del mensaje, que es HTML.

        Mandarlo tal cual le llegaba a Sagui como «<p>¿Cómo anulo…</p>»: las etiquetas entraban en
        la consulta del retrieval y quedaban guardadas en la auditoría, donde se leen crudas. Se
        vio al abrir por primera vez la lista de consultas: la columna «Pregunta» tenía etiquetas
        en las del livechat y no en las del DM.
        """
        canal = self._canal_livechat()
        visto = []
        with self._post({"status": "answered", "body": "<p>Respuesta.</p>"}, visto):
            self.paso_consulta._process_answer(
                canal, "<p>¿Cómo anulo una <b>factura</b> enviada a DGI?</p>")
        pregunta = visto[0][1]["message"]
        self.assertNotIn("<", pregunta, "ni una etiqueta")
        self.assertIn("¿Cómo anulo una", pregunta)
        self.assertIn("enviada a DGI?", pregunta)

    def test_un_mensaje_vacio_no_llega_a_sagui(self):
        canal = self._canal_livechat()
        visto = []
        with self._post({"status": "answered", "body": "<p>x</p>"}, visto):
            self.paso_consulta._process_answer(canal, "<p><br></p>")
        self.assertEqual(visto, [], "un mensaje en blanco no es una consulta")

    def test_el_guion_no_avanza_y_atiende_una_segunda_pregunta(self):
        """Lo que convierte un guion de pasos fijos en una conversación."""
        canal = self._canal_livechat()
        visto = []
        with self._post({"status": "answered", "body": "<p>Respuesta.</p>"}, visto):
            paso = self.paso_consulta._process_answer(canal, "primera")
            paso._process_answer(canal, "segunda")
        self.assertEqual([p["message"] for _r, p in visto], ["primera", "segunda"])

    def test_el_correo_que_dejo_el_visitante_viaja_a_sagui(self):
        """Es la promesa del primer paso: si cierra el chat, igual le respondemos."""
        canal = self._canal_livechat()
        canal.message_post(body=Markup("<p>vicky.cliente@ejemplo.com</p>"),
                           message_type="comment", subtype_xmlid="mail.mt_comment")
        visto = []
        with self._post({"status": "answered", "body": "<p>Respuesta.</p>"}, visto):
            self.paso_consulta._process_answer(canal, "¿cómo anulo una factura?")
        self.assertEqual(visto[0][1]["user"]["email"], "vicky.cliente@ejemplo.com")

    def test_sin_correo_no_se_rompe_nada(self):
        canal = self._canal_livechat()
        visto = []
        with self._post({"status": "answered", "body": "<p>Respuesta.</p>"}, visto):
            self.paso_consulta._process_answer(canal, "¿cómo anulo una factura?")
        self.assertEqual(visto[0][1]["user"]["email"], "")

    # ================================================== la derivación
    def test_si_sagui_deriva_se_dispara_el_pase_a_un_operador(self):
        canal = self._canal_livechat()
        pases = []
        with self._post({"status": "escalated",
                         "body": "<p>Lo derivé a Vicky, te respondo por acá.</p>"}), \
             patch.object(type(self.paso_operador), "_process_step_forward_operator",
                          lambda self_, c: pases.append(c)):
            self.paso_consulta._process_answer(canal, "¿cuánto sale la licencia?")

        self.assertEqual(pases, [canal], "el pase nativo es la razón de usar chatbot.script")
        self.assertIn("derivé", canal.message_ids[0].body,
                      "y el visitante tiene que enterarse en el mismo chat")

    def test_una_respuesta_normal_no_dispara_el_pase(self):
        canal = self._canal_livechat()
        pases = []
        with self._post({"status": "answered", "body": "<p>Respuesta.</p>"}), \
             patch.object(type(self.paso_operador), "_process_step_forward_operator",
                          lambda self_, c: pases.append(c)):
            self.paso_consulta._process_answer(canal, "¿cómo anulo una factura?")
        self.assertEqual(pases, [], "derivar a una persona cuando la documentación alcanzaba "
                                    "es el peor error posible de este agente")

    # ================================================== la presentación del paso
    def test_el_paso_se_presenta_una_sola_vez(self):
        """«Contame en qué te puedo ayudar.» después de cada respuesta es un bot que no escucha."""
        canal = self._canal_livechat()
        with self._post({"status": "answered", "body": "<p>Respuesta.</p>"}):
            primera = self.paso_consulta._process_step(canal)
            self.assertTrue(primera, "la primera vez sí se presenta")
            # el `chatbot.message` que marca el paso lo deja el propio `_chatbot_post_message`
            segunda = self.paso_consulta._process_step(canal)
        self.assertFalse(segunda, "la segunda vuelta no vuelve a presentarse")
        self.assertEqual(canal.chatbot_current_step_id, self.paso_consulta,
                         "pero el guion tiene que seguir parado en este paso")

    def test_los_demas_pasos_se_publican_normal(self):
        correo = self.env.ref("forum_sagui_support.step_sagui_correo")
        self.assertTrue(correo._process_step(self._canal_livechat()))

    # ================================================== los límites
    def test_un_paso_de_otro_guion_no_pasa_por_sagui(self):
        otro = self.env["chatbot.script"].create({"title": "Otro guion"})
        paso = self.env["chatbot.script.step"].create({
            "chatbot_script_id": otro.id, "sequence": 1,
            "step_type": "free_input_multi", "message": "Contame"})
        canal = self._canal_livechat()
        visto = []
        with self._post({"status": "answered", "body": "<p>x</p>"}, visto):
            paso._process_answer(canal, "hola")
        self.assertEqual(visto, [], "este módulo sólo atiende su propio guion")

    def test_un_paso_que_no_es_de_conversacion_no_pasa_por_sagui(self):
        canal = self._canal_livechat()
        visto = []
        with self._post({"status": "answered", "body": "<p>x</p>"}, visto):
            self.env.ref("forum_sagui_support.step_sagui_correo")._process_answer(
                canal, "vicky@ejemplo.com")
        self.assertEqual(visto, [])

    def test_si_sagui_falla_el_chat_no_se_rompe(self):
        """El visitante está mirando la pantalla: una traza acá es un chat colgado."""
        canal = self._canal_livechat()
        with patch.object(type(self.env["sagui.relay"]), "preguntar",
                          side_effect=RuntimeError("boom")):
            siguiente = self.paso_consulta._process_answer(canal, "¿cómo anulo una factura?")
        self.assertEqual(siguiente, self.paso_consulta, "el guion sigue en pie")
