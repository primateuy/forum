# -*- coding: utf-8 -*-
# Lo único que se configura de este lado: dónde está Sagui y con qué token. Nada de umbrales, ni
# de documentación, ni de responsables: todo eso vive en Sagui, que es quien sabe.
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    sagui_url = fields.Char(
        string="URL de Sagui", config_parameter="forum_sagui_support.url",
        help="Base, sin barra final. Ej: https://sagui.primate.uy")
    sagui_token = fields.Char(
        string="Token", config_parameter="forum_sagui_support.token",
        help="Lo emite Sagui por cliente. Queda en ir.config_parameter, legible por cualquier "
             "administrador de esta base: si se filtra, se regenera del lado de Sagui.")
    sagui_timeout = fields.Integer(
        string="Timeout (s)", config_parameter="forum_sagui_support.timeout", default=20)
    sagui_longpoll_wait = fields.Integer(
        string="Long-poll (s)", config_parameter="forum_sagui_support.longpoll_wait", default=0,
        help="0 lo desactiva y queda el sondeo de una vez por minuto. Con un valor —25 es lo que "
             "Sagui admite como máximo— el cron sostiene la conexión y las respuestas del "
             "responsable llegan en segundos. Ocupa un hilo del cron worker mientras espera.")
    sagui_fallback_user_id = fields.Many2one(
        "res.users", string="Responsable local",
        config_parameter="forum_sagui_support.fallback_user_id",
        help="A quién se le deja la actividad cuando Sagui no responde. Es el único caso en que "
             "este módulo decide algo: si Sagui está caído, no puede decirnos a quién derivar.")
