# -*- coding: utf-8 -*-
# La comprobación del canal del sitio.
#
# El test que importa es `test_caza_el_regex_que_no_matchea`: es el defecto REAL que se encontró el
# 12-sep-2026 —`regex_url = '^/$'`, que nunca coincide porque ese campo se compara contra el Referer,
# una URL completa—, puesto de nuevo a propósito. Si la comprobación no lo caza, no sirve para nada:
# ese defecto ya convivió con toda la suite en verde.
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

BASE = "https://forum.ejemplo.uy"


@tagged("post_install", "-at_install", "forum_sagui")
class TestVerificacionCanal(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("web.base.url", BASE)
        cls.guion = cls.env.ref("forum_sagui_support.chatbot_script_sagui")
        cls.operador = cls.env["res.users"].create(
            {"name": "Operadora verif", "login": "operadora_verif_test"})
        cls.canal = cls.env["im_livechat.channel"].create({
            "name": "Soporte del sitio (test)",
            "user_ids": [(6, 0, [cls.operador.id])],
        })
        # Las reglas de otros canales no tienen por qué desaparecer, pero las de ESTE se controlan.
        cls.regla = cls.env["im_livechat.channel.rule"].create({
            "channel_id": cls.canal.id,
            "chatbot_script_id": cls.guion.id,
            "chatbot_only_if_no_operator": False,
            "action": "display_button",
            "regex_url": False,
        })
        cls.relay = cls.env["sagui.relay"]

    def _otras_reglas_fuera(self):
        """Las reglas de otros canales que apunten al guion enturbian el diagnóstico del test."""
        self.env["im_livechat.channel.rule"].sudo().search([
            ("chatbot_script_id", "=", self.guion.id), ("id", "!=", self.regla.id),
        ]).unlink()

    def _diagnostico(self):
        self._otras_reglas_fuera()
        return self.relay._diagnosticar_canal_sitio()

    # ================= el caso bueno =================
    def test_bien_configurado_no_reporta_nada(self):
        problemas, detalle = self._diagnostico()
        self.assertFalse(problemas, "una regla correcta no puede dar problemas: %s" % problemas)
        self.assertIn("Soporte del sitio (test)", detalle)

    # ================= EL defecto real =================
    def test_caza_el_regex_que_no_matchea(self):
        """`^/$` contra un Referer (`https://forum.ejemplo.uy/`) no coincide NUNCA.

        Es el defecto que estuvo puesto en la base de pruebas y que convivió con toda la suite en
        verde: el módulo instalaba, los tests pasaban, el endpoint respondía, y el chat del sitio
        no tenía bot.
        """
        self.regla.regex_url = "^/$"
        problemas, _d = self._diagnostico()
        self.assertTrue(problemas, "el regex que no matchea pasó desapercibido, que es el punto")
        texto = " ".join(problemas)
        self.assertIn("ninguna regla coincide", texto)
        self.assertIn("^/$", texto, "el aviso tiene que decir cuál es el valor que está mal")
        self.assertIn("vacío", texto, "y cuál es el valor correcto")

    def test_un_regex_que_SI_matchea_no_molesta(self):
        """No alcanza con avisar siempre: el chequeo tiene que distinguir. `/$` sí coincide."""
        self.regla.regex_url = "/$"
        problemas, _d = self._diagnostico()
        self.assertFalse(problemas, "`/$` coincide con la portada y no tenía que dar problema: %s"
                         % problemas)

    # ================= las otras causas, cada una con su mensaje =================
    def test_sin_bot_de_chat_en_ninguna_regla(self):
        self._otras_reglas_fuera()
        self.regla.chatbot_script_id = False
        problemas, _d = self.relay._diagnosticar_canal_sitio()
        self.assertTrue(problemas)
        self.assertIn("Ningún canal", " ".join(problemas))

    def test_solo_si_no_hay_operador_avisa(self):
        self.regla.chatbot_only_if_no_operator = True
        problemas, _d = self._diagnostico()
        self.assertIn("Solo si no hay operador", " ".join(problemas))

    def test_boton_oculto_avisa(self):
        self.regla.action = "hide_button"
        problemas, _d = self._diagnostico()
        self.assertIn("ocultar el botón", " ".join(problemas))

    def test_guion_sin_pasos_avisa(self):
        self.guion.script_step_ids.unlink()
        problemas, _d = self._diagnostico()
        self.assertIn("no tiene pasos", " ".join(problemas))

    def test_gana_otra_regla_avisa(self):
        """Con varias reglas, `match_rule` devuelve la primera que coincide. Si esa no es la nuestra,
        el visitante no ve a Sagui aunque la regla de Sagui exista y esté perfecta."""
        self._otras_reglas_fuera()
        self.env["im_livechat.channel.rule"].create({
            "channel_id": self.canal.id, "regex_url": False, "action": "display_button",
            "sequence": 1,
        })
        self.regla.sequence = 99
        problemas, _d = self.relay._diagnosticar_canal_sitio()
        self.assertIn("gana otra regla", " ".join(problemas))

    def test_sin_web_base_url_lo_dice(self):
        self.env["ir.config_parameter"].sudo().set_param("web.base.url", "")
        problemas, _d = self._diagnostico()
        self.assertIn("web.base.url", " ".join(problemas))

    # ================= el botón =================
    def test_el_boton_levanta_UserError_cuando_esta_roto(self):
        self.regla.regex_url = "^/$"
        self._otras_reglas_fuera()
        ajustes = self.env["res.config.settings"].create({})
        with self.assertRaises(UserError) as e:
            ajustes.action_verificar_canal_sitio()
        self.assertIn("Manual de uso", str(e.exception),
                      "el aviso tiene que decir dónde está explicado cómo arreglarlo")

    def test_el_boton_no_molesta_cuando_esta_bien(self):
        self._otras_reglas_fuera()
        accion = self.env["res.config.settings"].create({}).action_verificar_canal_sitio()
        self.assertEqual(accion["params"]["type"], "success")

    def test_el_aviso_del_arranque_no_levanta_nunca(self):
        """Cuelga del post_init del módulo: si levantara, rompería la instalación."""
        self.regla.regex_url = "^/$"
        self.relay._avisar_si_el_canal_esta_roto()   # no debe levantar
        self.env["ir.config_parameter"].sudo().set_param("web.base.url", "")
        self.relay._avisar_si_el_canal_esta_roto()
