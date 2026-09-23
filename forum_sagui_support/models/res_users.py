# -*- coding: utf-8 -*-
# Siembra del DM, igual que hace OdooBot.
#
# Hace falta porque el usuario del bot está ARCHIVADO —para no consumir licencia— y
# `res.partner.im_search` (mail/models/res_partner.py:335) filtra `('active','=',True)` sobre
# res.users. O sea: por más que exista, nadie lo encuentra en «Nuevo mensaje». La solución que usa
# Odoo para su propio bot es no depender de la búsqueda: dejarle el DM ya creado a cada usuario.
import logging

from markupsafe import Markup

from odoo import _, api, models

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = "res.users"

    def _init_messaging(self):
        """Se llama al abrir Discuss. Es el momento en que un usuario nuevo recibe su DM."""
        if self and not self.env.context.get("sagui_sin_siembra"):
            try:
                self._sagui_sembrar_dm()
            except Exception:  # noqa: BLE001
                _logger.exception("Sagui soporte: no pude sembrar el DM")
        return super()._init_messaging()

    def _sagui_sembrar_dm(self):
        """Crea el DM con Sagui y deja el saludo. Idempotente: si ya existe, no hace nada."""
        self.ensure_one()
        bot = self.env.ref("forum_sagui_support.partner_sagui_soporte", raise_if_not_found=False)
        if not bot or self.partner_id == bot or self.share:
            return
        # `channel_get` agrega SIEMPRE el partner del usuario actual y revienta con más de dos
        # (`mail/models/discuss/discuss_channel.py:926`). Si esto corriera como admin —que es lo
        # que pasa en el post_init, recorriendo a todos los usuarios— serían tres: bot, destino y
        # admin. Se llama COMO el usuario destino y se pasa sólo el bot.
        canal = self.env["discuss.channel"].with_user(self).channel_get([bot.id])
        if not canal:
            return
        canal = self.env["discuss.channel"].sudo().browse(canal["id"])
        ya = self.env["mail.message"].sudo().search_count([
            ("model", "=", "discuss.channel"), ("res_id", "=", canal.id),
            ("author_id", "=", bot.id)])
        if ya:
            return
        canal.sudo().message_post(
            body=self._sagui_saludo(), author_id=bot.id,
            message_type="comment", subtype_xmlid="mail.mt_comment")

    @api.model
    def _sagui_saludo(self):
        """El primer mensaje que van a ver TODOS los usuarios el día del deploy.

        Por eso no es un «hola» genérico: explica qué es, qué puede hacer, qué no, y qué pasa
        cuando no sabe. Un bot que aparece sin presentarse en la lista de conversaciones de alguien
        genera más preguntas de las que responde.
        """
        return Markup("<p>%s</p><p>%s</p><p>%s</p><p><i>%s</i></p>") % (
            _("¡Hola! Soy Sagui, el asistente de soporte."),
            _("Podés preguntarme por acá cómo se hacen las cosas en el sistema: facturación, "
              "remitos, stock, accesos. Respondo con la documentación del equipo y te digo "
              "siempre en qué documento me basé."),
            _("Si algo no está documentado, no me lo invento: derivo tu consulta a la persona que "
              "corresponda y te aviso acá mismo con quién quedó. La respuesta te llega en esta "
              "misma conversación."),
            _("Escribime cuando quieras. No hace falta que abras un ticket."),
        )


def archivar_bot(env):
    """Archiva el usuario del bot DESPUÉS de crearlo, no al crearlo.

    Creado con `active=False`, el valor viaja al partner por el _inherits y queda un contacto dado
    de baja como autor de todos los mensajes del bot. Archivado con un write posterior, no
    cascadea: verificado sobre la base —usuario=False, partner=True—.
    """
    usuario = env.ref("forum_sagui_support.user_sagui_soporte", raise_if_not_found=False)
    partner = env.ref("forum_sagui_support.partner_sagui_soporte", raise_if_not_found=False)
    if partner and not partner.active:
        partner.sudo().write({"active": True})
    if usuario and usuario.active:
        usuario.sudo().write({"active": False})


def post_init_sembrar_dm(env):
    """Al instalar: archivar el bot y sembrarle el DM a los internos que YA existen.

    `_init_messaging` cubre a los que entren después; sin esto, los usuarios actuales tendrían que
    esperar a su próximo login y algunos no lo verían nunca.
    """
    archivar_bot(env)
    usuarios = env["res.users"].search([("share", "=", False), ("active", "=", True)])
    for usuario in usuarios:
        try:
            usuario._sagui_sembrar_dm()
        except Exception:  # noqa: BLE001
            _logger.exception("Sagui soporte: falló la siembra para %s", usuario.login)
    # Y de paso: si la regla del canal del sitio quedó sin entregar el guion, que quede dicho en el
    # log del deploy. Es configuración a mano y cuando está mal no falla nada —ver
    # `verificacion_canal.py`—, así que el único momento garantizado para avisar es éste.
    env["sagui.relay"]._avisar_si_el_canal_esta_roto()
    _logger.info("Sagui soporte: DM sembrado para %s usuarios", len(usuarios))
