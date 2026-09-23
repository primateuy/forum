# -*- coding: utf-8 -*-
# El núcleo compartido por las dos entradas. Todo lo que este módulo sabe hacer está acá:
# preguntarle a Sagui, publicar lo que conteste, y traerse lo que Sagui haya dejado para el usuario.
#
# No hay una sola regla de negocio en este archivo. Si algo parece una decisión —a quién derivar,
# si hay cobertura, cuándo cerrar— está del otro lado, a propósito: duplicarla acá sería tener dos
# versiones de la verdad y descubrir la diferencia con un cliente adelante.
import json
import logging
import time
import urllib.error
import urllib.request

from markupsafe import Markup

import odoo
from odoo import SUPERUSER_ID, _, api, models
from odoo.service.model import retrying
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


def enviar(cfg, ruta, payload, timeout=None):
    """El POST pelado, sin ORM. Está aparte para poder llamarlo desde un `postcommit`, donde el
    cursor ya está confirmado y no conviene volver a tocar la base."""
    req = urllib.request.Request(
        "%s%s" % (cfg["url"], ruta),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer %s" % cfg["token"]},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout or cfg["timeout"]) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


class SaguiRelay(models.AbstractModel):
    _name = "sagui.relay"
    _description = "Puente con el agente de soporte de Sagui"

    # ==================================================================
    @api.model
    def _config(self):
        get = self.env["ir.config_parameter"].sudo().get_param
        return {
            "url": (get("forum_sagui_support.url") or "").rstrip("/"),
            "token": get("forum_sagui_support.token") or "",
            "timeout": int(get("forum_sagui_support.timeout") or 20),
            "fallback": int(get("forum_sagui_support.fallback_user_id") or 0),
            "longpoll_wait": int(get("forum_sagui_support.longpoll_wait") or 0),
        }

    @api.model
    def _post(self, ruta, payload, timeout=None):
        """POST JSON a Sagui. Devuelve el dict, o levanta.

        `timeout` se pasa aparte para el long-poll: el de /ask (20 s) es un tope de paciencia, y el
        del /outbox retenido tiene que ser MAYOR al tiempo que Sagui sostiene la conexión, o Forum
        corta siempre antes de que llegue la respuesta y el long-poll no funciona nunca. Se usa
        urllib y no `requests` para no sumarle una dependencia al Odoo del cliente por tres
        llamadas HTTP.
        """
        cfg = self._config()
        if not cfg["url"] or not cfg["token"]:
            raise UserWarning(_("Falta configurar la URL o el token de Sagui."))
        return enviar(cfg, ruta, payload, timeout)

    # ==================================================================
    @api.model
    def preguntar(self, canal, conversation_ref, mensaje, usuario=None):
        """Le pregunta a Sagui y publica la respuesta en el mismo hilo. Nunca deja el hilo mudo."""
        self._escribiendo(canal, True)
        try:
            datos = self._post("/sagui/support/ask", {
                "conversation_ref": conversation_ref,
                "message": mensaje,
                "user": usuario or {},
                "history": self._historial(canal),
            })
        except Exception as e:  # noqa: BLE001
            _logger.warning("Sagui soporte: no pude consultar a Sagui (%s)", e)
            self._escribiendo(canal, False)
            return self._caida(canal, conversation_ref, mensaje, e)

        cuerpo = datos.get("body")
        if cuerpo:
            self.publicar(canal, cuerpo)
        # El apagado va por la transacción normal, no aparte: así viaja en el mismo lote de
        # notificaciones que el mensaje. Apagarlo antes dejaría un hueco visible —el indicador se
        # va, la respuesta todavía no llegó— justo en el momento en que el usuario está mirando.
        self._escribiendo(canal, False, aparte=False)
        return datos

    # ------------------------------------------------------------------
    @api.model
    def _escribiendo(self, canal, activo, aparte=True):
        """Prende o apaga el «Sagui está escribiendo…» del hilo.

        POR QUÉ UNA TRANSACCIÓN APARTE (`aparte=True`)
        `bus.bus._sendone` no manda nada en el momento: encola el registro en el `precommit` y el
        `NOTIFY` en el `postcommit` del cursor. O sea que **una notificación emitida dentro de esta
        transacción se entrega recién cuando la transacción termina**, que es exactamente el
        instante en que también se entrega la respuesta. Prendido y apagado llegarían juntos,
        después del hecho: el indicador no se vería nunca. Por eso el encendido se emite sobre un
        cursor propio que commitea ahí mismo, antes de la llamada HTTP que tarda los 2-6 segundos
        que el indicador existe para cubrir.

        El cursor aparte sólo inserta en `bus_bus` y lee el miembro del canal; no toca ninguna fila
        que la transacción de afuera tenga tomada, así que no hay riesgo de bloqueo mutuo.

        POR QUÉ NO HAY QUE LIMPIARLO
        El estado de «escribiendo» no se guarda en ningún lado: es una notificación y nada más. Si
        el proceso se muere con el indicador prendido, el front lo saca solo a los 60 s
        (`OTHER_LONG_TYPING` en `mail/static/src/discuss/typing/common/typing_service.js`). Un
        indicador colgado es un detalle estético con vencimiento, no un estado corrupto.

        Falla en silencio a propósito: esto es cortesía, y no hay ninguna cortesía que valga
        romperle la respuesta al usuario.
        """
        if not canal:
            return
        try:
            bot = self._bot_partner()
            if not aparte:
                self._marcar_escribiendo(self.env, canal.id, bot.id, activo)
                return
            with odoo.registry(self.env.cr.dbname).cursor() as cr:
                self._marcar_escribiendo(api.Environment(cr, SUPERUSER_ID, {}),
                                         canal.id, bot.id, activo)
        except Exception:  # noqa: BLE001
            _logger.debug("Sagui soporte: no pude mandar el indicador de escritura",
                          exc_info=True)

    @api.model
    def _marcar_escribiendo(self, env, canal_id, bot_id, activo):
        miembro = env["discuss.channel.member"].sudo().search(
            [("channel_id", "=", canal_id), ("partner_id", "=", bot_id)], limit=1)
        if miembro:
            # `_notify_typing` avisa al canal y también al `uuid`, que es por donde escucha el
            # visitante del livechat. La misma llamada sirve para las dos entradas.
            miembro._notify_typing(activo)

    @api.model
    def publicar(self, canal, cuerpo, autor=None):
        """Publica en el hilo como el bot.

        `Markup` y no str: desde Odoo 16 `message_post` escapa un cuerpo de texto plano, y lo que
        manda Sagui YA es HTML. Sin esto el usuario ve las etiquetas.
        """
        partner = self._bot_partner()
        return canal.sudo().message_post(
            body=Markup(cuerpo or ""),
            author_id=(autor or partner).id,
            message_type="comment",
            subtype_xmlid="mail.mt_comment")

    # ==================================================================
    @api.model
    def _caida(self, canal, conversation_ref, mensaje, error):
        """Sagui no contestó. El usuario recibe algo digno y queda una actividad local.

        Es el único lugar donde este módulo decide por su cuenta, y es deliberado: si Sagui está
        caído, no hay a quién preguntarle a quién derivar. El silencio no es una opción — alguien
        está esperando del otro lado de un chat.
        """
        self.publicar(canal, Markup("<p>%s</p>") % _(
            "Estoy con problemas para consultar la documentación en este momento. Ya avisé a "
            "alguien del equipo para que lo vea."))
        cfg = self._config()
        if cfg["fallback"]:
            try:
                # La actividad NO va sobre el canal, va sobre el contacto del responsable.
                #
                # Al crear una actividad, Odoo avisa al asignado con un `message_notify` SOBRE EL
                # REGISTRO de la actividad. Con el canal como registro, ese aviso se publica en el
                # hilo del usuario: quien preguntó veía un «Apreciable Soporte PrimateUy SAS,
                # Pedro Martínez le acaba de asignar la siguiente actividad» en su propio chat,
                # justo después de que le dijéramos que estábamos con problemas. Se vio grabando
                # la demo, que es la única forma de ver una cosa así.
                usuario = self.env["res.users"].sudo().browse(cfg["fallback"])
                self.env["mail.activity"].sudo().create({
                    "res_model_id": self.env["ir.model"]._get("res.partner").id,
                    "res_id": usuario.partner_id.id,
                    "activity_type_id": self.env.ref("mail.mail_activity_data_todo").id,
                    "user_id": cfg["fallback"],
                    "summary": _("Consulta de soporte sin responder (Sagui no disponible)"),
                    "note": Markup("<p>%s</p><p>%s</p><p><i>%s</i></p>") % (
                        _("En el hilo «%s»:") % (canal.name or canal.id),
                        mensaje, str(error)[:200]),
                })
            except Exception:  # noqa: BLE001
                _logger.exception("Sagui soporte: tampoco pude crear la actividad local")
        return {"status": "error", "body": None}

    # ==================================================================
    @api.model
    def _historial(self, canal, limite=6):
        """Los últimos turnos del hilo, para que Sagui entienda una repregunta.

        «¿Y eso cómo?» después de «no puedo anular una factura» es una pregunta clara; sin el
        historial es una pregunta vacía que termina pidiéndole al usuario que reformule algo que
        ya dijo.
        """
        partner = self._bot_partner()
        mensajes = self.env["mail.message"].sudo().search(
            [("model", "=", "discuss.channel"), ("res_id", "=", canal.id),
             ("message_type", "=", "comment")], order="id desc", limit=limite)
        salida = []
        for m in reversed(mensajes):
            salida.append({
                "role": "assistant" if m.author_id == partner else "user",
                "body": (m.body or "")[:1000],
            })
        return salida

    @api.model
    def _bot_partner(self):
        return self.env.ref("forum_sagui_support.partner_sagui_soporte")

    # ==================================================================
    #  Cola de salida
    # ==================================================================
    @api.model
    def _cron_traer_respuestas(self):
        """El ÚNICO lugar que sostiene conexiones largas, y por eso está acotado.

        QUIÉN LO SOSTIENE
        Este cron, y nadie más. No se hace long-poll desde la petición del usuario: retener 25 s la
        petición que trae su mensaje le congelaría el chat. Acá, en cambio, lo que se ocupa es un
        hilo del cron worker, que no tiene a nadie esperando del otro lado.

        UNA VUELTA POR EJECUCIÓN, Y SE RE-DISPARA
        La versión anterior hacía el bucle ADENTRO de una sola ejecución, y eso significaba tener
        UNA transacción abierta 50-75 s sobre datos calientes. Publicar toca
        `discuss_channel_member`; el navegador del usuario le escribe `seen_message_id` a la misma
        fila cada vez que mira el hilo. Medido el 12-sep-2026: el cron publicó la respuesta a las
        17:05:20 y a las 17:06:10 —con el mensaje hacía rato en la pantalla— el job murió con
        `SerializationFailure` y se deshizo todo lo de la vuelta.

        Con `_trigger()` cada vuelta es una ejecución propia, con su transacción corta y su commit:
        un choque cuesta una vuelta, no un ciclo. Y el ack de lo publicado sale en ese commit,
        que es lo que hace que «al menos una vez» sea verdad.

        CÓMO SE DEGRADA
        Con `longpoll_wait` en 0 —o si Sagui contesta al instante y sin nada, porque no le quedan
        peticiones retenidas disponibles— no se re-dispara y queda el sondeo simple de una vez por
        minuto. El piso sigue siendo el mismo pase lo que pase; el long-poll sólo baja la latencia
        cuando hay cupo.

        Un reinicio de Odoo a mitad de una conexión retenida no pierde nada: el cursor sólo avanza
        después de publicar, y lo que Sagui vuelva a mandar lo filtra el dedup por `seq`.
        """
        cfg = self._config()
        espera = cfg["longpoll_wait"]
        if espera <= 0:
            return self.traer_respuestas(wait=0)

        antes = time.monotonic()
        # `retrying` es el mismo mecanismo con el que Odoo reintenta una petición HTTP que chocó:
        # hace rollback, resetea el registro y vuelve a llamar, hasta 5 veces. Acá hace falta
        # porque publicar en un canal que alguien ESTÁ MIRANDO choca de verdad —el navegador del
        # usuario le escribe `seen_message_id` a la misma fila de `discuss_channel_member`— y el
        # cron, a diferencia de una petición HTTP, no reintenta solo: el job muere y lo publicado
        # se deshace. Sin esto, cada choque le cuesta al usuario un ciclo entero de espera.
        total = retrying(lambda: self.traer_respuestas(wait=espera), self.env)
        if total or time.monotonic() - antes >= 1:
            # O entregó algo, o la retención funcionó: en los dos casos vale la pena volver a
            # ponerse a escuchar ya. Si volvió vacío y al instante, no hay long-poll disponible e
            # insistir sería un bucle apretado contra su endpoint.
            cron = self.env.ref("forum_sagui_support.cron_sagui_traer_respuestas",
                                raise_if_not_found=False)
            if cron:
                cron.sudo()._trigger()
        return total

    @api.model
    def traer_respuestas(self, wait=0):
        """Trae la cola de Sagui y publica cada mensaje en su hilo. Devuelve cuántos publicó."""
        Param = self.env["ir.config_parameter"].sudo()
        cursor = int(Param.get_param("forum_sagui_support.cursor") or 0)
        try:
            # Margen sobre lo que Sagui va a retener: si el timeout del cliente fuera igual o
            # menor, la carrera la gana siempre el corte y el long-poll no sirve de nada.
            datos = self._post("/sagui/support/outbox", {"cursor": cursor, "wait": wait},
                               timeout=(wait + 10) if wait else None)
        except Exception as e:  # noqa: BLE001
            _logger.warning("Sagui soporte: no pude leer la cola (%s)", e)
            return 0

        publicados, ultimo = 0, cursor
        for msg in datos.get("messages") or []:
            seq = int(msg.get("seq") or 0)
            if seq <= cursor:
                continue
            if self._ya_publicado(seq):
                # Entrega al menos una vez: si se publicó y el ack no llegó, Sagui lo vuelve a
                # mandar. Publicarlo de nuevo sería mostrarle al usuario la misma respuesta dos
                # veces, así que se deduplica acá, que es donde se sabe.
                ultimo = max(ultimo, seq)
                continue
            canal = self._canal_de(msg.get("conversation_ref") or "")
            if canal and not self._sesion_muerta(canal):
                self.publicar(canal, msg.get("body") or "")
                publicados += 1
            else:
                # Puede haber canal Y no haber a quién mostrarle nada: una sesión de livechat
                # cerrada NO borra el canal. Ver `_sesion_muerta`.
                if self._sin_hilo(msg, canal):
                    publicados += 1
            self._marcar_publicado(seq)
            ultimo = max(ultimo, seq)

        if ultimo > cursor:
            Param.set_param("forum_sagui_support.cursor", str(ultimo))
            self._confirmar_al_commitear(ultimo)
        return publicados

    @api.model
    def _confirmar_al_commitear(self, cursor):
        """Agenda el ack para DESPUÉS del commit, y por eso no se manda acá mismo.

        «Al menos una vez» se apoya en una condición fácil de romper: el ack no puede salir antes
        de que lo publicado esté EN FIRME. Si sale antes y la transacción se cae después, Sagui lo
        dio por entregado y no lo repite: el mensaje no se demora, se PIERDE.

        Y la transacción se cae. Medido dos veces el 12-sep-2026 grabando la demo: el cron publicó
        la respuesta del responsable y ~50 s después el job murió con `SerializationFailure` sobre
        `discuss_channel_member` —el usuario estaba MIRANDO el hilo y su navegador le escribía
        `seen_message_id` a la misma fila—. El `message_post` se deshizo, el cursor se deshizo, el
        ack ya había salido. El hilo quedó con la derivación y después el cierre, sin la respuesta
        en el medio. Publicar en un canal que alguien está mirando es el caso NORMAL de un chat.

        El primer intento fue confirmar «lo de la vuelta anterior» al empezar la siguiente, y NO
        alcanzaba: `_cron_traer_respuestas` llama a `traer_respuestas` varias veces DENTRO DE LA
        MISMA transacción, así que la vuelta anterior tampoco estaba commiteada y el cursor que se
        leía salía del cache del ORM. La única señal confiable de que algo quedó en firme es el
        commit, así que el ack se cuelga de ahí.

        La configuración se captura ANTES: dentro del `postcommit` la transacción ya cerró y no es
        momento de volver a consultar la base.
        """
        cfg = self._config()

        def ack():
            try:
                enviar(cfg, "/sagui/support/ack", {"cursor": cursor})
            except Exception as e:  # noqa: BLE001
                # Se pierde el ack y Sagui repetirá. No pasa nada: el dedup por `seq` lo cubre.
                _logger.warning("Sagui soporte: no pude confirmar la cola (%s)", e)

        self.env.cr.postcommit.add(ack)

    # ------------------------------------------------------------------
    # Una MARCA ALTA, no una fila por mensaje. Antes esto escribía un `ir.config_parameter` llamado
    # `forum_sagui_support.publicado.<seq>` por cada respuesta entregada, y nada las borraba nunca:
    # un cliente activo dejaba miles de filas para siempre en una tabla que Odoo lee y cachea de
    # forma agresiva, para guardar un booleano que ya estaba implícito en el orden.
    #
    # Se puede colapsar en un solo número porque el bucle de `traer_respuestas` marca TODOS los seq
    # que procesa —entregados, entregados por correo y los que no se pudieron entregar—, así que el
    # conjunto de marcados nunca tiene huecos: es siempre «todo hasta N». Preguntar `seq <= N` es
    # exactamente la misma pregunta que antes.
    #
    # Y NO es lo mismo que `cursor`, aunque hoy valgan igual. `cursor` es lo que Forum le DICE a
    # Sagui que ya tiene: se manda en `/outbox` y en `/ack`, y es el que alguien retrocede a mano
    # para volver a bajar una cola que quedó trabada (el README avisa que no se toque sin saber por
    # qué, lo cual significa que se toca). Esta marca es lo que de verdad se le PUSO DELANTE A UN
    # USUARIO, y por eso tiene que sobrevivir a ese retroceso: es la única cosa que impide que
    # reencolar una cola le muestre a alguien la misma respuesta dos veces.
    CLAVE_PUBLICADO = "forum_sagui_support.publicado_hasta"

    @api.model
    def _ya_publicado(self, seq):
        return seq <= int(
            self.env["ir.config_parameter"].sudo().get_param(self.CLAVE_PUBLICADO) or 0)

    @api.model
    def _marcar_publicado(self, seq):
        """Sube la marca. Nunca la baja: que un lote venga desordenado no puede reabrir la puerta."""
        Param = self.env["ir.config_parameter"].sudo()
        actual = int(Param.get_param(self.CLAVE_PUBLICADO) or 0)
        if seq > actual:
            Param.set_param(self.CLAVE_PUBLICADO, str(seq))

    @api.model
    def _canal_de(self, conversation_ref):
        """Resuelve el hilo a partir del identificador que este mismo módulo armó."""
        partes = (conversation_ref or "").split(":")
        if len(partes) < 3 or partes[0] != "forum":
            return None
        clave = partes[2]
        if partes[1] == "dm":
            return self.env["discuss.channel"].sudo().browse(int(clave)).exists()
        if partes[1] == "livechat":
            return self.env["discuss.channel"].sudo().search([("uuid", "=", clave)], limit=1)
        return None

    @api.model
    def _sesion_muerta(self, canal):
        """¿Publicar en este canal le llega a alguien?

        La trampa: cerrar una sesión de livechat NO borra el canal. `_close_livechat_session` sólo
        pone `livechat_active = False` (`im_livechat/models/discuss_channel.py:120`), así que el
        canal sigue existiendo y `_canal_de` lo encuentra perfecto. Publicar ahí no falla, no
        loguea nada y no lo lee nadie: el visitante cerró la pestaña y el widget no vuelve.

        Por eso la pregunta no es «¿existe el canal?» sino «¿hay alguien del otro lado?». Un DM de
        Discuss siempre tiene a alguien —queda en la bandeja del usuario y lo va a ver cuando
        vuelva—; una sesión de livechat cerrada, no.
        """
        return canal.channel_type == "livechat" and not canal.livechat_active

    @api.model
    def _sin_hilo(self, msg, canal=None):
        """El hilo ya no recibe a nadie. La respuesta sale por correo. Devuelve si se entregó.

        Es la promesa que se le hizo al visitante cuando dejó el correo en el primer paso del
        chatbot: si no lo hubiera dejado, se le avisó en el momento que no íbamos a poder
        responderle si cerraba el chat. Cumplirla o no es la diferencia entre un agente que deriva
        y un agente que pierde consultas.
        """
        ref = msg.get("conversation_ref") or ""
        correo = self._correo_del_visitante(canal) if canal else ""
        if not correo:
            # Sin correo no hay a dónde mandarlo. Se publica igual en el canal si existe: no se le
            # muestra a nadie ahora, pero queda en el historial de la sesión —que el operador SÍ ve
            # desde el backend— en vez de evaporarse. El aviso de que esto podía pasar ya se lo dio
            # el guion cuando el visitante decidió no dejar el correo.
            if canal:
                self.publicar(canal, msg.get("body") or "")
                _logger.info(
                    "Sagui soporte: sesión muerta y sin correo en %s — la respuesta queda en el "
                    "canal para el operador", ref)
                return True
            _logger.warning("Sagui soporte: sin hilo y sin correo para %s: la respuesta se pierde",
                            ref)
            return False

        asunto = self._asunto_de(canal, msg)
        cuerpo = self._cuerpo_del_correo(canal, msg)
        correo_id = self.env["mail.mail"].sudo().create({
            "subject": asunto,
            "body_html": cuerpo,
            "email_to": correo,
            "auto_delete": False,
            # `email_from` explícito: sin un `mail.alias.domain` configurado, Odoo arma un
            # Return-Path con el `False` de la compañía adentro y el envío muere con «Malformed
            # 'Return-Path' or 'From' address». No es hipotético: pasa hoy en esta base.
            "email_from": (self.env.company.email
                           or self.env["ir.config_parameter"].sudo().get_param("mail.default.from")
                           or self.env.user.email_formatted),
        })
        correo_id.send(raise_exception=False)
        _logger.info("Sagui soporte: respuesta de %s enviada por correo a %s", ref, correo)
        if canal:
            # Queda también en el canal, con la nota de que salió por correo: es lo que ve el
            # operador cuando abre la sesión y se pregunta en qué terminó.
            self.publicar(canal, Markup("<p><i>%s</i></p>") % (
                _("La sesión ya estaba cerrada: esta respuesta se le envió a %s por correo.")
                % correo))
        return True

    @api.model
    def _asunto_de(self, canal, msg):
        """El asunto REFERENCIA LA CONSULTA. Un «Respuesta de soporte» a secas, días después y en
        una bandeja llena, no se abre: quien pregunta no se acuerda de qué se trataba.

        Hay que filtrar POR AUTOR y no por largo. Medido en vivo el 12-sep-2026: con el filtro de
        «primer mensaje de más de 25 caracteres» el asunto salió «Tu consulta: ¡Hola! Soy Sagui.
        Respondo con la documentación del equipo…», o sea el saludo del propio bot. Los pasos del
        guion son largos, y quien pregunta rara vez escribe más que ellos.

        El visitante es el que NO es ninguno de los dos operadores: en una sesión de livechat sus
        mensajes van sin `author_id` y con `author_guest_id` —es un invitado, no un usuario—, pero
        si entró logueado sí tiene partner. Por eso se excluye a los operadores en vez de exigir
        que sea un invitado.
        """
        pregunta = ""
        if canal:
            ajenos = canal.livechat_operator_id
            paso = canal.chatbot_current_step_id or self.env["chatbot.script.step"]
            if paso.chatbot_script_id:
                ajenos |= paso.chatbot_script_id.operator_partner_id
            # El guion pudo haber terminado y dejado `chatbot_current_step_id` vacío: se rescata el
            # bot por sus propios mensajes del canal, que es de donde salía el asunto equivocado.
            bot = self.env.ref("forum_sagui_support.partner_sagui_soporte",
                               raise_if_not_found=False)
            if bot:
                ajenos |= bot
            mensajes = self.env["mail.message"].sudo().search(
                [("model", "=", "discuss.channel"), ("res_id", "=", canal.id),
                 ("message_type", "=", "comment"),
                 ("author_id", "not in", ajenos.ids)], order="id")
            for m in mensajes:
                plano = " ".join(html2plaintext(m.body or "").split())
                # Lo que queda es del visitante. Se saltea el correo que dejó en el primer paso.
                if plano and "@" not in plano:
                    pregunta = plano
                    break
        if pregunta:
            return _("Tu consulta: %s") % (pregunta[:70] + ("…" if len(pregunta) > 70 else ""))
        return _("Respuesta a tu consulta de soporte")

    @api.model
    def _cuerpo_del_correo(self, canal, msg):
        quien = msg.get("assigned_to") or ""
        encabezado = (_("<p>Hola, te escribimos porque cerraste el chat antes de que "
                        "pudiéramos responderte. Esto es lo que te contesta %s:</p>") % quien
                      if quien else
                      _("<p>Hola, te escribimos porque cerraste el chat antes de que pudiéramos "
                        "responderte. Esto es lo que averiguamos:</p>"))
        pie = _("<hr/><p style='color:#888'>Si necesitás seguir, respondé este correo o volvé a "
                "escribirnos por el chat del sitio.</p>")
        return Markup(encabezado) + Markup(msg.get("body") or "") + Markup(pie)

    @api.model
    def _correo_del_visitante(self, canal):
        """El correo que el primer paso del guion le pidió al visitante.

        Vive acá y no en `chatbot_script_step` porque lo necesitan los dos: el paso del guion, para
        pasárselo a Sagui con la consulta, y la vuelta por correo, para saber a dónde escribir.
        """
        if not canal:
            return ""
        mensaje = self.env["mail.message"].sudo().search([
            ("model", "=", "discuss.channel"), ("res_id", "=", canal.id),
            ("body", "like", "@")], order="id", limit=1)
        cuerpo = html2plaintext(mensaje.body) if mensaje else ""
        for palabra in (cuerpo or "").split():
            if "@" in palabra and "." in palabra:
                return palabra.strip(".,;:<>")
        return ""
