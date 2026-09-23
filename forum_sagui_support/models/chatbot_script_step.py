# -*- coding: utf-8 -*-
# Entrada 2: livechat del sitio.
#
# Se usa `chatbot.script` y no un operador-bot por una razón concreta: `_process_step_forward_operator`
# da el pase a un humano de forma nativa, que es exactamente lo que hace falta cuando Sagui deriva
# y hay un operador conectado. Con un operador-bot habría que reimplementar ese pase a mano.
import logging

from odoo import _, api, models
from odoo.exceptions import ValidationError
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class ChatbotScriptStep(models.Model):
    _inherit = "chatbot.script.step"

    # ==================================================================
    #  Protección del guion
    # ==================================================================
    @api.constrains("sequence", "step_type", "chatbot_script_id")
    def _check_orden_sagui(self):
        """El pase a operador tiene que ir DESPUÉS de la conversación.

        Se valida la RELACIÓN entre los dos pasos sobre el guion completo, no el registro que se
        acaba de escribir. La primera versión miraba sólo el paso forward y tenía dos agujeros:

        1. **El camino inverso.** Mover la CONVERSACIÓN después del forward produce el mismo flujo
           roto sin tocar el registro del forward, así que la comprobación nunca corría.
        2. **La escritura en lote.** La manija de arrastre del editor
           (`im_livechat/views/chatbot_script_step_views.xml:35`) reescribe `sequence` sobre varios
           pasos de una vez. Validar registro por registro, aislado, no ve el estado final: hay que
           mirar el guion entero una vez que todo quedó escrito.

        Por qué importa el orden: ese paso no se alcanza siguiendo el guion —el de conversación
        nunca avanza, `_process_answer` devuelve `self`— y el módulo lo busca por `step_type`, no
        por posición. Reordenar es inocuo salvo en un caso: si el forward queda antes, el guion lo
        alcanza solo y TODOS los visitantes terminan derivados a una persona antes de preguntar
        nada.
        """
        guion = self.env.ref("forum_sagui_support.chatbot_script_sagui",
                             raise_if_not_found=False)
        if not guion or not (self.chatbot_script_id & guion):
            return

        # Se relee el guion COMPLETO: lo que importa es el estado final, venga de donde venga el
        # write. `@api.constrains` corre después del flush, así que esto ya ve los valores nuevos.
        pasos = guion.script_step_ids
        forwards = pasos.filtered(lambda p: p.step_type == "forward_operator")
        conversacion = pasos.filtered(lambda p: p.step_type == "free_input_multi")
        if not forwards or not conversacion:
            return

        # El forward va después de TODOS los pasos de conversación. `<=` y no `<` porque dos pasos
        # con la misma secuencia dejan el orden a merced del id, que es lo mismo que no definirlo.
        if min(forwards.mapped("sequence")) <= max(conversacion.mapped("sequence")):
            raise ValidationError(_(
                "En el guion «%s», el paso de pase a un operador tiene que ir DESPUÉS del paso "
                "de conversación.\n\n"
                "No es decorativo: ese paso no se alcanza siguiendo el guion, lo invoca el módulo "
                "cuando Sagui deriva una consulta y hay un operador conectado. Si queda antes, el "
                "guion lo alcanza solo y todos los visitantes terminan derivados a una persona "
                "antes de poder preguntar nada."
            ) % guion.title)

    def _process_answer(self, discuss_channel, message_body):
        """Cada mensaje libre del visitante pasa por Sagui y la respuesta se publica en el canal.

        NO se avanza de paso: el chatbot queda en bucle conversacional sobre este mismo paso, que
        es lo que convierte un guion de pasos fijos en una conversación.
        """
        res = super()._process_answer(discuss_channel, message_body)
        if self.step_type != "free_input_multi" or not self._es_paso_de_sagui():
            return res
        try:
            self._sagui_atender(discuss_channel, message_body)
        except Exception:  # noqa: BLE001
            _logger.exception("Sagui soporte: error atendiendo el livechat")
        return self                      # quedarse en este paso

    def _process_step(self, discuss_channel):
        """El paso de conversación se presenta UNA vez, no en cada vuelta.

        `_process_answer` devuelve `self` a propósito —es lo que mantiene la conversación abierta
        en este paso— y el frontend, después de cada mensaje, vuelve a procesar el paso. El
        `_process_step` de base publica el `message` del paso cada vez, así que el visitante leía
        «Contame en qué te puedo ayudar.» **después de cada respuesta de Sagui**, como si no
        hubiera entendido nada de lo que acababa de contestar.

        Se reconoce por `chatbot.message`, que es el registro que el propio chatbot deja por cada
        mensaje suyo con el paso al que corresponde: si ya hay uno de este paso en este canal, la
        presentación ya se hizo. Devolver `False` es lo que la base ya hace cuando un paso no
        publica nada (`chatbot_posted_message` queda en `None`), así que el frontend lo maneja.
        """
        if self.step_type == "free_input_multi" and self._es_paso_de_sagui():
            ya = self.env["chatbot.message"].sudo().search_count([
                ("discuss_channel_id", "=", discuss_channel.id),
                ("script_step_id", "=", self.id)])
            if ya:
                discuss_channel.chatbot_current_step_id = self.id
                return False
        return super()._process_step(discuss_channel)

    def _es_paso_de_sagui(self):
        guion = self.env.ref("forum_sagui_support.chatbot_script_sagui",
                             raise_if_not_found=False)
        return bool(guion) and self.chatbot_script_id == guion

    def _sagui_atender(self, canal, mensaje):
        relay = self.env["sagui.relay"]
        # `_process_answer` recibe el BODY del mensaje, que es HTML. Mandarlo así le llegaba a
        # Sagui como «<p>¿Cómo anulo una factura?</p>»: las etiquetas entran en la consulta del
        # retrieval y quedan guardadas en la auditoría, donde se ven crudas. Se descubrió mirando
        # la lista de consultas: la columna «Pregunta» del livechat tenía etiquetas y la del DM no.
        texto = html2plaintext(mensaje or "").strip()
        if not texto:
            return
        datos = relay.preguntar(
            canal, "forum:livechat:%s" % canal.uuid, texto,
            usuario={"name": canal.anonymous_name or "", "email": self._correo_del_visitante(canal)})
        if datos.get("status") == "escalated":
            # Si hay un operador conectado, el pase es nativo. Si no hay, el usuario ya recibió el
            # aviso de que quedó derivado y la respuesta le va a llegar por la cola.
            paso_operador = self.env["chatbot.script.step"].search([
                ("chatbot_script_id", "=", self.chatbot_script_id.id),
                ("step_type", "=", "forward_operator")], limit=1)
            if paso_operador:
                paso_operador._process_step_forward_operator(canal)
            else:
                # El aviso de que quedó derivado ya se lo dio Sagui, así que el usuario no queda
                # sin respuesta. Pero sin el paso no hay pase a un humano, y eso hay que saberlo.
                _logger.warning(
                    "Sagui soporte: no encontré el paso de pase a operador en el guion; la "
                    "consulta quedó derivada pero sin traspaso en vivo.")

    def _correo_del_visitante(self, canal):
        """El correo que el primer paso del guion le pidió al visitante.

        La implementación vive en `sagui.relay`: la necesitan los dos lados —este paso, para
        pasárselo a Sagui con la consulta, y la vuelta por correo, para saber a dónde escribir— y
        dos copias de la misma heurística se desincronizan el día que alguien mejora una.
        """
        return self.env["sagui.relay"]._correo_del_visitante(canal)
