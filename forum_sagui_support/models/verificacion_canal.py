# -*- coding: utf-8 -*-
# Comprobación del canal del sitio: ¿la regla del livechat le está entregando el guion a Sagui?
#
# POR QUÉ EXISTE ESTO. La regla que conecta el guion con el sitio (`im_livechat.channel.rule`) es
# configuración A MANO en cada alta de cliente: no viaja en los datos del módulo porque depende del
# canal de livechat de cada uno. Y cuando queda mal, **no falla nada**: el módulo instala, los tests
# pasan en verde, el endpoint responde. Lo único que pasa es que el chat del sitio deja de tener bot
# y los visitantes caen en un operador humano —o no ven la burbuja—, que es justo lo que uno no mira
# cuando todo lo demás está bien.
#
# Pasó de verdad, el 12-sep-2026: `regex_url` en `^/$`, que NUNCA matchea porque ese campo se compara
# contra el Referer —una URL completa— y no contra la ruta. El síntoma no se parecía a una regla mal
# escrita: se parecía a una limitación de Odoo.
#
# La comprobación replica la decisión de `im_livechat/controllers/main.py::livechat_init` en vez de
# volver a pegarle por HTTP: usa el `match_rule` DE ODOO —la misma función que corre en la petición
# real— y después aplica las mismas condiciones. Pegarle por HTTP obligaría a que el servidor se
# alcance a sí mismo por la red, que es una fuente de falsos negativos que no tiene nada que ver con
# lo que se quiere comprobar.
import logging

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MANUAL = "Manual de uso, Parte 3 → «La regla que conecta el guion con el sitio»"


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    def action_verificar_canal_sitio(self):
        """Botón: dice si el chat del sitio va a ser atendido por Sagui, y si no, por qué."""
        self.ensure_one()
        problemas, detalle = self.env["sagui.relay"]._diagnosticar_canal_sitio()
        if problemas:
            raise UserError("%s\n\n%s\n\nDónde arreglarlo: %s" % (
                _("El chat del sitio NO está atendido por Sagui."),
                "\n\n".join("• %s" % p for p in problemas), MANUAL))
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"type": "success", "sticky": False,
                       "title": _("El chat del sitio está atendido por Sagui"),
                       "message": detalle},
        }


class SaguiRelay(models.AbstractModel):
    _inherit = "sagui.relay"

    def _diagnosticar_canal_sitio(self):
        """Devuelve `(problemas, detalle)`. Lista vacía = el guion se está entregando.

        Cada condición se comprueba por separado y con su propio mensaje: «no anda» no sirve de nada
        cuando la causa puede ser el regex, el flag de operadores, el guion desactivado o que la
        regla ni siquiera existe.
        """
        guion = self.env.ref("forum_sagui_support.chatbot_script_sagui", raise_if_not_found=False)
        if not guion:
            return [_("No existe el guion de Sagui en esta base.")], ""

        Regla = self.env["im_livechat.channel.rule"].sudo()
        reglas = Regla.search([("chatbot_script_id", "=", guion.id)])
        if not reglas:
            return [_(
                "Ningún canal de chat en vivo tiene a «%s» como bot de chat. Sin eso, quien entre "
                "por el sitio habla directamente con una persona.") % guion.title], ""

        base = (self.env["ir.config_parameter"].sudo().get_param("web.base.url") or "").rstrip("/")
        if not base:
            return [_("Falta `web.base.url`: sin la dirección del sitio no se puede comprobar "
                      "contra qué URL matchea la regla.")], ""
        url = base + "/"

        problemas = []
        detalle = []
        for regla in reglas:
            canal = regla.channel_id
            # 1. ¿La regla que GANA para la portada es la nuestra? Es la pregunta central: puede
            #    haber varias reglas y `match_rule` devuelve la primera que matchea.
            ganadora = Regla.match_rule(canal.id, url, country_id=False)
            if not ganadora:
                problemas.append(_(
                    "Canal «%(c)s»: ninguna regla coincide con %(u)s. La regla de Sagui tiene "
                    "URL = «%(r)s», y ese campo se compara contra la dirección COMPLETA de la "
                    "página, no contra la parte de después del dominio: un valor como «^/$» no "
                    "coincide con ninguna página. Dejalo vacío.",
                    c=canal.name, u=url, r=regla.regex_url or ""))
                continue
            if ganadora != regla:
                problemas.append(_(
                    "Canal «%(c)s»: para %(u)s gana otra regla (URL «%(o)s») antes que la de "
                    "Sagui (URL «%(r)s»), y esa otra no tiene bot de chat.",
                    c=canal.name, u=url, o=ganadora.regex_url or "", r=regla.regex_url or ""))
                continue
            # 2. Las condiciones que `livechat_init` exige para meter el chatbot en la respuesta.
            if not guion.active:
                problemas.append(_("El guion «%s» está archivado.") % guion.title)
                continue
            if not guion.script_step_ids:
                problemas.append(_("El guion «%s» no tiene pasos.") % guion.title)
                continue
            if regla.chatbot_only_if_no_operator:
                problemas.append(_(
                    "Canal «%s»: está marcado «Solo si no hay operador», así que Sagui sólo "
                    "atiende cuando no hay nadie conectado. Para que atienda siempre, "
                    "desmarcalo.") % canal.name)
                continue
            if regla.action == "hide_button":
                problemas.append(_(
                    "Canal «%s»: la acción de la regla es «ocultar el botón», así que el visitante "
                    "no tiene cómo abrir el chat.") % canal.name)
                continue
            detalle.append(_("Canal «%(c)s»: %(n)s pasos, atiende siempre.",
                             c=canal.name, n=len(guion.script_step_ids)))
        return problemas, "\n".join(detalle)

    def _avisar_si_el_canal_esta_roto(self):
        """Lo mismo, al log, para que quede en el arranque y no dependa de que alguien mire.

        Va como WARNING y con el síntoma primero: quien lea el log después de un deploy tiene que
        poder reconocerlo sin saber nada de reglas de livechat.
        """
        try:
            problemas, _detalle = self._diagnosticar_canal_sitio()
        except Exception:  # noqa: BLE001
            _logger.exception("Sagui soporte: no pude comprobar el canal del sitio")
            return
        for p in problemas:
            _logger.warning(
                "Sagui soporte: EL CHAT DEL SITIO NO LO ATIENDE SAGUI — %s (ver %s)", p, MANUAL)
