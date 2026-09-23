# -*- coding: utf-8 -*-
# Entrada 1: DM de Discuss. Mismo patrón que `mail_bot._apply_logic` y que el bot de Sagui en v19.
import logging

from odoo import models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    _inherit = "discuss.channel"

    def _message_post_after_hook(self, message, msg_vals):
        res = super()._message_post_after_hook(message, msg_vals)
        try:
            self._sagui_soporte_responder(message, msg_vals)
        except Exception:  # noqa: BLE001
            # Nunca romper el message_post del usuario por culpa del puente: su mensaje ya está
            # escrito y tiene que quedar, falle lo que falle después.
            #
            # Pero que no rompa NO significa que pase desapercibido: este except dejó al bot mudo
            # durante una prueba punta a punta por un KeyError de un modelo inexistente, y desde
            # afuera se veía igual que "Sagui no tenía nada que decir". Por eso el mensaje empieza
            # con el síntoma observable, no con la causa.
            _logger.exception(
                "Sagui soporte: EL BOT NO RESPONDIÓ en el canal %s — falló el relay del DM",
                self.id)
        return res

    def _sagui_soporte_responder(self, message, msg_vals):
        self.ensure_one()
        if self.channel_type != "chat":
            return                                   # fase 1: sólo DM. Menciones, fase 2.
        bot = self.env.ref("forum_sagui_support.partner_sagui_soporte", raise_if_not_found=False)
        if not bot or bot not in self.channel_member_ids.partner_id:
            return
        autor = msg_vals.get("author_id") or message.author_id.id
        if not autor or autor == bot.id:
            return                                   # guardia anti-recursión
        if (msg_vals.get("message_type") or message.message_type) != "comment":
            return

        # `html2plaintext` de odoo.tools y no un rodeo por ir.fields.converter: es la utilidad
        # estándar y no depende de que exista un modelo. La versión anterior levantaba KeyError,
        # el except de arriba se lo tragaba, y el bot quedaba mudo sin que nada lo dijera.
        texto = html2plaintext(message.body or "")
        if not texto.strip():
            return
        self.env["sagui.relay"].preguntar(
            self, "forum:dm:%s" % self.id, texto,
            usuario={"name": message.author_id.name,
                     "email": message.author_id.email or "",
                     "external_id": "res.partner,%s" % message.author_id.id})
