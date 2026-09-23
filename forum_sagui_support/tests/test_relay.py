# -*- coding: utf-8 -*-
# El puente: DM, cola, dedup, caída de Sagui y los límites del bot. Sagui se simula: este módulo
# no tiene que hablar con nadie para que sus tests valgan.
import json
from unittest.mock import patch

from markupsafe import Markup

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "forum_sagui")
class TestRelay(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bot = cls.env.ref("forum_sagui_support.partner_sagui_soporte")
        cls.bot_user = cls.env.ref("forum_sagui_support.user_sagui_soporte")
        cls.usuario = cls.env["res.users"].create(
            {"name": "Pedro Forum", "login": "pedro_forum_test"})
        Param = cls.env["ir.config_parameter"].sudo()
        Param.set_param("forum_sagui_support.url", "http://sagui.test")
        Param.set_param("forum_sagui_support.token", "tok")
        # El cursor de la cola se pone en 0 A PROPÓSITO, y no es higiene: sin esto los tests
        # dependen de lo que haya quedado COMMITEADO en la base. Una prueba en vivo dejó el cursor
        # en 47 y dos tests de dedup —que usan seq 7 y 21— empezaron a fallar sin que nadie tocara
        # el código: los seq quedaron por debajo del cursor y se descartaban. Un test que sólo pasa
        # en una base virgen no dice nada sobre el código.
        Param.set_param("forum_sagui_support.cursor", "0")
        # Y por el mismo motivo se baja la marca de dedup. Antes era un parámetro por `seq`
        # —`publicado.7`— y uno que quedara de una corrida anterior hacía fallar el test del dedup
        # sin que nadie hubiera tocado el código. (Uno quedó de verdad, el 12-sep-2026, por un
        # `cr.commit()` que se coló en una versión del relay: un commit dentro de un test no es un
        # detalle de aislamiento, ESCRIBE en la base.) Ahora es UNA marca alta, así que alcanza con
        # ponerla en cero. Esto corre dentro de la transacción del test y se deshace al terminar.
        Param.set_param(cls.env["sagui.relay"].CLAVE_PUBLICADO, "0")
        # Y se barren las viejas por si la base viene de antes de la migración 17.0.1.0.4.
        Param.search([("key", "=like", "forum_sagui_support.publicado.%")]).unlink()
        cls.relay = cls.env["sagui.relay"]

    def _canal_dm(self):
        # Como el usuario destino, pasando sólo el bot: channel_get suma el partner del usuario
        # actual y rechaza más de dos.
        info = self.env["discuss.channel"].with_user(self.usuario).channel_get([self.bot.id])
        return self.env["discuss.channel"].sudo().browse(info["id"])

    # ================================================== el bot
    def test_el_usuario_bot_esta_archivado_pero_su_partner_no(self):
        """Archivado para no consumir licencia; el partner ACTIVO para poder publicar y verse bien.

        Archivar el usuario archiva también su partner —`active` viaja por el _inherits—, y un
        partner archivado se ve como un contacto dado de baja en cada mensaje del bot. El dato lo
        reactiva después de crear el usuario, y este test fija que siga así.
        """
        self.assertFalse(self.bot_user.active, "no puede consumir licencia")
        self.assertTrue(self.bot.active, "pero su contacto tiene que estar vivo")

    def test_el_bot_no_lee_datos_de_negocio(self):
        """El módulo relaya, no consulta. El usuario del bot no tiene por qué poder leer nada.

        Si algún día alguien le agrega grupos "por comodidad", este test lo frena.
        """
        for modelo in ("account.move", "sale.order", "stock.picking", "res.partner"):
            if modelo not in self.env:
                continue
            with self.assertRaises(AccessError, msg="el bot no puede leer %s" % modelo):
                self.env[modelo].with_user(self.bot_user).search([], limit=1).read()

    def test_el_bot_no_es_operador_de_livechat(self):
        """El pase a un humano tiene que dar con una PERSONA, no con el bot."""
        canales = self.env["im_livechat.channel"].search([])
        self.assertNotIn(self.bot_user, canales.user_ids)

    # ================================================== siembra
    def test_la_siembra_deja_el_dm_con_la_presentacion(self):
        self.usuario._sagui_sembrar_dm()
        canal = self._canal_dm()
        mensajes = self.env["mail.message"].sudo().search([
            ("model", "=", "discuss.channel"), ("res_id", "=", canal.id),
            ("author_id", "=", self.bot.id)])
        self.assertTrue(mensajes, "el DM tiene que venir con el saludo: el bot está archivado y "
                                  "no aparece en la búsqueda de «Nuevo mensaje»")
        cuerpo = mensajes[0].body
        self.assertIn("Sagui", cuerpo)
        self.assertIn("derivo", cuerpo, "tiene que decir qué hace cuando no sabe")
        self.assertNotIn("&lt;p&gt;", cuerpo, "el saludo no puede llegar escapado")

    def test_la_siembra_es_idempotente(self):
        self.usuario._sagui_sembrar_dm()
        self.usuario._sagui_sembrar_dm()
        canal = self._canal_dm()
        n = self.env["mail.message"].sudo().search_count([
            ("model", "=", "discuss.channel"), ("res_id", "=", canal.id),
            ("author_id", "=", self.bot.id)])
        self.assertEqual(n, 1, "instalar dos veces no puede saludar dos veces")

    # ================================================== cola y dedup
    def _sin_retrying(self):
        """Deja pasar la llamada sin la maquinaria de reintento de Odoo.

        `odoo.service.model.retrying` termina con `env.cr.commit()` —commitea y corre los
        post-commits, que es justo lo que se quiere en el cron— y eso, dentro de una
        `TransactionCase`, destruye el savepoint del test y hace caer la clase entera. Los tests
        prueban NUESTRA lógica; que `retrying` reintente y commitee es de Odoo, y lo que se fija
        acá es que la vuelta pase por ahí (ver `test_el_cron_publica_con_reintento`).
        """
        import odoo.addons.forum_sagui_support.models.sagui_relay as mod
        return patch.object(mod, "retrying", lambda func, env: func())

    def _respuesta(self, mensajes, cursor):
        return {"messages": mensajes, "cursor": cursor}

    def test_dedup_por_seq(self):
        """Entrega al menos una vez: si el ack se pierde, Sagui repite. Se publica UNA vez."""
        canal = self._canal_dm()
        msg = {"seq": 7, "conversation_ref": "forum:dm:%s" % canal.id,
               "kind": "escalation_answer", "body": "<p>Son 20 días.</p>"}
        antes = len(canal.message_ids)

        with patch.object(type(self.relay), "_post") as post:
            post.return_value = self._respuesta([msg], 7)
            self.assertEqual(self.relay.traer_respuestas(), 1)
        with patch.object(type(self.relay), "_post") as post:
            post.return_value = self._respuesta([msg], 7)   # Sagui lo repite
            self.assertEqual(self.relay.traer_respuestas(), 0, "no se publica dos veces")

        self.assertEqual(len(canal.message_ids), antes + 1)

    def test_un_reinicio_a_mitad_no_pierde(self):
        """El cursor sólo avanza DESPUÉS de publicar, así que lo no publicado vuelve."""
        canal = self._canal_dm()
        msg = {"seq": 11, "conversation_ref": "forum:dm:%s" % canal.id,
               "kind": "escalation_answer", "body": "<p>Respuesta que estaba en vuelo.</p>"}
        Param = self.env["ir.config_parameter"].sudo()
        Param.set_param("forum_sagui_support.cursor", "0")

        # el proceso se cae antes de publicar: el cursor sigue en 0
        self.assertEqual(int(Param.get_param("forum_sagui_support.cursor") or 0), 0)

        with patch.object(type(self.relay), "_post") as post:
            post.return_value = self._respuesta([msg], 11)
            self.assertEqual(self.relay.traer_respuestas(), 1, "al volver, se publica")
        self.assertEqual(int(Param.get_param("forum_sagui_support.cursor")), 11)

    def test_el_cuerpo_no_llega_escapado(self):
        canal = self._canal_dm()
        with patch.object(type(self.relay), "_post") as post:
            post.return_value = self._respuesta([{
                "seq": 21, "conversation_ref": "forum:dm:%s" % canal.id,
                "kind": "escalation_answer",
                "body": "<p>Son <b>20 días</b> hábiles.</p>"}], 21)
            self.relay.traer_respuestas()
        cuerpo = canal.message_ids[0].body
        self.assertIn("<b>20 días</b>", cuerpo)
        self.assertNotIn("&lt;b&gt;", cuerpo)

    def test_el_ack_NO_sale_durante_la_transaccion(self):
        """El ack se cuelga del commit. Mientras la transacción vive, no salió nada.

        Es la condición de la que depende «al menos una vez»: si el ack sale antes de que lo
        publicado esté en firme y después la transacción se cae, Sagui lo da por entregado y no lo
        repite. Pasó dos veces grabando la demo, con un `SerializationFailure` sobre
        `discuss_channel_member` medio minuto después de publicar.

        `TestCursor` ignora los `postcommit` a propósito, así que el test los corre a mano: eso es
        exactamente lo que hace el commit de verdad.
        """
        canal = self._canal_dm()
        rutas = []

        def falso_post(self_, ruta, payload, timeout=None):
            rutas.append((ruta, payload.get("cursor")))
            if ruta == "/sagui/support/outbox":
                return self._respuesta([{
                    "seq": 621, "conversation_ref": "forum:dm:%s" % canal.id,
                    "kind": "escalation_answer", "body": "<p>Una.</p>"}], 621)
            return {}

        import odoo.addons.forum_sagui_support.models.sagui_relay as mod
        enviados = []
        with patch.object(type(self.relay), "_post", falso_post), \
             patch.object(mod, "enviar", lambda cfg, ruta, payload, timeout=None:
                          enviados.append((ruta, payload.get("cursor"))) or {}):
            self.relay.traer_respuestas()
            self.assertEqual(enviados, [], "durante la transacción NO se confirma nada")
            self.env.cr.postcommit.run()
            self.assertEqual(enviados, [("/sagui/support/ack", 621)],
                             "y al commitear, sí")

    def test_si_la_transaccion_se_cae_no_queda_ack_pendiente(self):
        """Rollback: los `postcommit` no corren, así que Sagui repite y nada se pierde."""
        canal = self._canal_dm()

        def falso_post(self_, ruta, payload, timeout=None):
            if ruta == "/sagui/support/outbox":
                return self._respuesta([{
                    "seq": 631, "conversation_ref": "forum:dm:%s" % canal.id,
                    "kind": "escalation_answer", "body": "<p>La que casi se pierde.</p>"}], 631)
            return {}

        import odoo.addons.forum_sagui_support.models.sagui_relay as mod
        enviados = []
        with patch.object(type(self.relay), "_post", falso_post), \
             patch.object(type(self.relay), "publicar", side_effect=Exception("choque")), \
             patch.object(mod, "enviar", lambda cfg, ruta, payload, timeout=None:
                          enviados.append(ruta) or {}), \
             self.assertRaises(Exception):
            self.relay.traer_respuestas()

        self.env.cr.postrollback.run()
        self.env.cr.postcommit.clear()
        self.assertEqual(enviados, [], "sin publicar no se confirma NADA")

    # ================================================== caída de Sagui
    def test_si_sagui_no_responde_el_hilo_no_queda_mudo(self):
        canal = self._canal_dm()
        self.env["ir.config_parameter"].sudo().set_param(
            "forum_sagui_support.fallback_user_id", str(self.env.ref("base.user_admin").id))
        antes = len(canal.message_ids)

        with patch.object(type(self.relay), "_post", side_effect=OSError("timeout")):
            self.relay.preguntar(canal, "forum:dm:%s" % canal.id, "¿cómo anulo una factura?")

        self.assertEqual(len(canal.message_ids), antes + 1, "el usuario tiene que recibir algo")
        self.assertIn("problemas", canal.message_ids[0].body)
        admin = self.env.ref("base.user_admin")
        actividad = self.env["mail.activity"].search([
            ("res_model", "=", "res.partner"), ("res_id", "=", admin.partner_id.id),
            ("user_id", "=", admin.id)])
        self.assertTrue(actividad, "y tiene que quedar una actividad local para una persona")
        self.assertIn(canal.name or str(canal.id), actividad[0].note,
                      "la actividad tiene que decir en qué hilo fue")

    def test_el_aviso_interno_de_la_caida_no_se_publica_en_el_chat_del_usuario(self):
        """La actividad avisa al asignado publicando SOBRE SU REGISTRO.

        Con el canal como registro, ese aviso —«X le acaba de asignar la siguiente actividad»—
        aparecía en el hilo del usuario, justo después de decirle que teníamos problemas. Lo vio
        la grabación de la demo; ningún test lo miraba.
        """
        canal = self._canal_dm()
        self.env["ir.config_parameter"].sudo().set_param(
            "forum_sagui_support.fallback_user_id", str(self.env.ref("base.user_admin").id))

        with patch.object(type(self.relay), "_post", side_effect=OSError("timeout")):
            self.relay.preguntar(canal, "forum:dm:%s" % canal.id, "¿cómo anulo una factura?")

        internos = canal.message_ids.filtered(lambda m: m.message_type == "user_notification")
        self.assertFalse(
            internos, "el hilo del usuario no puede tener avisos internos: %s"
                      % internos.mapped("body")[:1])

    def test_la_cola_caida_no_rompe_el_cron(self):
        with patch.object(type(self.relay), "_post", side_effect=OSError("caído")):
            self.assertEqual(self.relay.traer_respuestas(), 0)

    # ================================================== el hook del DM, por el camino real
    def _hablarle_al_bot(self, canal, texto, autor=None, tipo="comment"):
        """Escribe en el canal como lo haría una persona: `message_post`, no llamar al relay.

        El hook es un override de `_message_post_after_hook`, y llamarlo por atrás prueba el relay
        pero no el enganche. La prueba en vivo mostró justo eso: el bot quedaba mudo por un error
        DENTRO del hook, con el relay perfectamente sano.
        """
        return canal.with_user(autor or self.usuario).message_post(
            body=Markup("<p>%s</p>") % texto, message_type=tipo,
            subtype_xmlid="mail.mt_comment")

    def test_un_dm_al_bot_dispara_la_respuesta(self):
        canal = self._canal_dm()
        preguntas = []

        def falso_post(self_, ruta, payload, timeout=None):
            preguntas.append(payload)
            return {"status": "answered", "body": "<p>Se anula con una nota de crédito.</p>"}

        with patch.object(type(self.relay), "_post", falso_post):
            self._hablarle_al_bot(canal, "¿cómo anulo una factura?")

        self.assertEqual(len(preguntas), 1, "el hook tiene que haber llamado a Sagui")
        self.assertEqual(preguntas[0]["conversation_ref"], "forum:dm:%s" % canal.id)
        self.assertEqual(preguntas[0]["message"], "¿cómo anulo una factura?",
                         "le llega el texto plano, sin el HTML del composer")
        self.assertEqual(preguntas[0]["user"]["name"], self.usuario.name)
        ultimo = canal.message_ids[0]
        self.assertEqual(ultimo.author_id, self.bot, "la respuesta la publica el bot")
        self.assertIn("nota de crédito", ultimo.body)

    def test_el_bot_no_se_contesta_a_si_mismo(self):
        """Sin la guardia anti-recursión, la respuesta del bot es un DM más y esto no para."""
        canal = self._canal_dm()
        llamadas = []

        def falso_post(self_, ruta, payload, timeout=None):
            llamadas.append(payload)
            return {"status": "answered", "body": "<p>Algo.</p>"}

        with patch.object(type(self.relay), "_post", falso_post):
            canal.sudo().message_post(body=Markup("<p>Hola</p>"), author_id=self.bot.id,
                                      message_type="comment", subtype_xmlid="mail.mt_comment")
        self.assertEqual(llamadas, [])

    def test_una_nota_interna_no_despierta_al_bot(self):
        canal = self._canal_dm()
        llamadas = []

        def falso_post(self_, ruta, payload, timeout=None):
            llamadas.append(payload)
            return {"status": "answered", "body": "<p>Algo.</p>"}

        with patch.object(type(self.relay), "_post", falso_post):
            self._hablarle_al_bot(canal, "una nota", tipo="notification")
        self.assertEqual(llamadas, [])

    def test_si_el_hook_explota_el_mensaje_del_usuario_igual_queda(self):
        """El except de `_message_post_after_hook` existe para esto, y hay que probarlo."""
        canal = self._canal_dm()
        antes = len(canal.message_ids)
        with patch.object(type(self.relay), "preguntar", side_effect=RuntimeError("boom")):
            self._hablarle_al_bot(canal, "¿cómo anulo una factura?")
        self.assertEqual(len(canal.message_ids), antes + 1,
                         "el mensaje del usuario ya estaba escrito: tiene que quedar")

    # ================================================== indicador de escritura
    def test_el_indicador_se_prende_ANTES_de_la_llamada_y_se_apaga_despues(self):
        """El orden es todo el punto: prenderlo después de esperar no sirve de nada.

        Se simula `_marcar_escribiendo` —no `_escribiendo`— porque lo que no se puede ejercitar en
        un test es el CURSOR APARTE: commitea de verdad, y en un test la transacción todavía no
        commiteó el canal, así que ese cursor no lo vería. La notificación en sí, que es el borde
        real, la prueba el test de abajo sobre el bus.
        """
        canal = self._canal_dm()
        eventos = []

        def marcar(self_, env, canal_id, bot_id, activo):
            eventos.append("typing:%s" % activo)

        def falso_post(self_, ruta, payload, timeout=None):
            eventos.append("http")
            return {"status": "answered", "body": "<p>Se anula con una nota de crédito.</p>"}

        with patch.object(type(self.relay), "_marcar_escribiendo", marcar), \
             patch.object(type(self.relay), "_post", falso_post):
            self.relay.preguntar(canal, "forum:dm:%s" % canal.id, "¿cómo anulo una factura?")

        self.assertEqual(eventos, ["typing:True", "http", "typing:False"])

    def test_el_indicador_sale_por_el_bus_como_el_miembro_bot(self):
        """El borde real: una notificación de `typing_status` del miembro que es el bot.

        Las filas del bus se crean en el `precommit`, así que hay que correrlo para verlas. Eso
        mismo —que no salga nada hasta el commit— es la razón de que el encendido vaya por un
        cursor aparte.
        """
        canal = self._canal_dm()
        self.env["bus.bus"].sudo().search([]).unlink()
        self.relay._marcar_escribiendo(self.env, canal.id, self.bot.id, True)
        self.env.cr.precommit.run()

        filas = self.env["bus.bus"].sudo().search([])
        tipos = [json.loads(f.message)["type"] for f in filas]
        self.assertIn("discuss.channel.member/typing_status", tipos)
        carga = [json.loads(f.message)["payload"] for f in filas
                 if json.loads(f.message)["type"] == "discuss.channel.member/typing_status"][0]
        self.assertTrue(carga["isTyping"])
        self.assertEqual(carga["persona"]["id"], self.bot.id,
                         "el que escribe tiene que ser el bot, no el usuario")

    def test_el_indicador_se_apaga_aunque_sagui_se_caiga(self):
        """Si no, queda escribiendo hasta que el front lo caduque a los 60 s."""
        canal = self._canal_dm()
        eventos = []

        def marcar(self_, env, canal_id, bot_id, activo):
            eventos.append(activo)

        with patch.object(type(self.relay), "_marcar_escribiendo", marcar), \
             patch.object(type(self.relay), "_post", side_effect=OSError("timeout")):
            self.relay.preguntar(canal, "forum:dm:%s" % canal.id, "¿cómo anulo una factura?")

        self.assertEqual(eventos, [True, False])

    def test_el_indicador_nunca_rompe_la_respuesta(self):
        """Es cortesía. Si el bus falla, el usuario igual tiene que recibir lo que preguntó."""
        canal = self._canal_dm()
        antes = len(canal.message_ids)

        def marcar(self_, env, canal_id, bot_id, activo):
            raise RuntimeError("el bus explotó")

        def falso_post(self_, ruta, payload, timeout=None):
            return {"status": "answered", "body": "<p>Se anula con una nota de crédito.</p>"}

        with patch.object(type(self.relay), "_marcar_escribiendo", marcar), \
             patch.object(type(self.relay), "_post", falso_post):
            self.relay.preguntar(canal, "forum:dm:%s" % canal.id, "¿cómo anulo una factura?")

        self.assertEqual(len(canal.message_ids), antes + 1)
        self.assertIn("nota de crédito", canal.message_ids[0].body)

    # ================================================== el piso de latencia
    def test_el_cron_de_la_cola_no_se_apaga_solo(self):
        """El cron es el piso: sin él, una respuesta del responsable se pierde, no se demora.

        Y se apagaba solo. `numbercall` por defecto es 1 en v17: el cron corría UNA vez, Odoo lo
        decrementaba a 0 y lo desactivaba. No falla nada, no se loguea nada — a los sesenta
        segundos de instalar el piso deja de existir en silencio. Se descubrió mirando por qué una
        conexión retenida no arrancaba nunca.
        """
        cron = self.env.ref("forum_sagui_support.cron_sagui_traer_respuestas")
        self.assertTrue(cron.active, "el cron tiene que estar vivo")
        self.assertEqual(cron.numbercall, -1,
                         "sin -1 el cron se autodestruye después de la primera corrida")

    # ================================================== long-poll
    def test_el_longpoll_usa_un_timeout_mayor_al_de_retencion(self):
        """Con el timeout de /ask (20 s) contra una retención de 25, siempre gana el corte."""
        capturado = {}

        def falso_post(self_, ruta, payload, timeout=None):
            capturado[ruta] = timeout
            return {"messages": [], "cursor": 0}

        with patch.object(type(self.relay), "_post", falso_post):
            self.relay.traer_respuestas(wait=25)
        self.assertGreater(capturado["/sagui/support/outbox"], 25)

    def test_el_cron_cae_al_piso_si_no_hay_longpoll(self):
        """Con el long-poll apagado queda el sondeo simple: una sola llamada, sin bucle."""
        self.env["ir.config_parameter"].sudo().set_param("forum_sagui_support.longpoll_wait", "0")
        llamadas = []

        def falso_post(self_, ruta, payload, timeout=None):
            llamadas.append(ruta)
            return {"messages": [], "cursor": 0}

        with patch.object(type(self.relay), "_post", falso_post):
            self.relay._cron_traer_respuestas()
        self.assertEqual(llamadas.count("/sagui/support/outbox"), 1)

    def test_despues_de_entregar_el_cron_vuelve_a_escuchar(self):
        """Entregar algo no es motivo para dejar de escuchar; es motivo para seguir.

        Cada vuelta es una ejecución propia del cron —transacción corta, commit propio— y la
        siguiente se pide con `_trigger()`. Antes el bucle vivía adentro de una sola ejecución:
        una transacción abierta un minuto sobre `discuss_channel_member`, que es la fila que el
        navegador del usuario está escribiendo mientras mira el hilo.
        """
        self.env["ir.config_parameter"].sudo().set_param("forum_sagui_support.longpoll_wait", "25")
        canal = self._canal_dm()
        disparos = []

        def falso_post(self_, ruta, payload, timeout=None):
            return self._respuesta([{"seq": 501,
                                     "conversation_ref": "forum:dm:%s" % canal.id,
                                     "kind": "escalation_answer",
                                     "body": "<p>Primera.</p>"}], 501)

        with self._sin_retrying(), patch.object(type(self.relay), "_post", falso_post), \
             patch.object(type(self.env["ir.cron"]), "_trigger",
                          lambda self_, at=None: disparos.append(self_.id)):
            self.relay._cron_traer_respuestas()
        self.assertEqual(len(disparos), 1, "después de entregar se vuelve a poner a escuchar")

    def test_el_cron_publica_con_reintento(self):
        """Publicar en un canal que alguien está mirando choca, y el cron no reintenta solo.

        Sin `retrying` el job muere, lo publicado se deshace y el usuario espera un ciclo entero.
        Medido dos veces el 12-sep-2026 grabando la demo, las dos con
        `SerializationFailure` sobre `discuss_channel_member`.

        El test comprueba que la vuelta pasa POR `retrying` y que igual publica. No provoca un
        choque de verdad a propósito: `retrying` hace `cr.rollback()`, que dentro de una
        `TransactionCase` se lleva puesta la transacción del test y hace caer la clase entera.
        """
        import odoo.addons.forum_sagui_support.models.sagui_relay as mod
        self.env["ir.config_parameter"].sudo().set_param("forum_sagui_support.longpoll_wait", "25")
        canal = self._canal_dm()
        envueltas = []

        def falso_post(self_, ruta, payload, timeout=None):
            return self._respuesta([{"seq": 701,
                                     "conversation_ref": "forum:dm:%s" % canal.id,
                                     "kind": "escalation_answer",
                                     "body": "<p>Con red de reintento.</p>"}], 701)

        def falso_retrying(func, env):
            envueltas.append(func)
            return func()

        with patch.object(type(self.relay), "_post", falso_post), \
             patch.object(mod, "retrying", falso_retrying), \
             patch.object(type(self.env["ir.cron"]), "_trigger", lambda self_, at=None: None):
            self.relay._cron_traer_respuestas()

        self.assertEqual(len(envueltas), 1, "la vuelta tiene que ir envuelta en `retrying`")
        self.assertIn("Con red de reintento", canal.message_ids[0].body)

    def test_el_cron_no_martilla_si_sagui_contesta_al_instante(self):
        """Vacía y al instante: no hay cupo de retenidas. Re-disparar sería un bucle apretado."""
        self.env["ir.config_parameter"].sudo().set_param("forum_sagui_support.longpoll_wait", "25")
        llamadas, disparos = [], []

        def falso_post(self_, ruta, payload, timeout=None):
            llamadas.append(ruta)
            return {"messages": [], "cursor": 0}

        with self._sin_retrying(), patch.object(type(self.relay), "_post", falso_post), \
             patch.object(type(self.env["ir.cron"]), "_trigger",
                          lambda self_, at=None: disparos.append(self_.id)):
            self.relay._cron_traer_respuestas()
        self.assertEqual(llamadas.count("/sagui/support/outbox"), 1)
        self.assertEqual(disparos, [], "una respuesta vacía e instantánea corta la cadena")
