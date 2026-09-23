# -*- coding: utf-8 -*-
# La marca de dedup: UN parámetro, no uno por mensaje.
#
# El defecto que esto cierra no era un fallo, era un crecimiento: `_marcar_publicado` escribía un
# `ir.config_parameter` llamado `forum_sagui_support.publicado.<seq>` por cada respuesta entregada y
# nada los borraba nunca. Con un cliente activo son miles de filas para siempre, en una tabla que
# Odoo lee y cachea de forma agresiva, para guardar un booleano que ya estaba implícito en el orden.
#
# Por eso el test central no mira un comportamiento: CUENTA FILAS. Un cambio que vuelva a escribir
# una clave por mensaje pasaría todos los tests de dedup y rompería sólo éste.
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "forum_sagui")
class TestMarcaDedup(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.relay = cls.env["sagui.relay"]
        cls.Param = cls.env["ir.config_parameter"].sudo()
        cls.Param.set_param(cls.relay.CLAVE_PUBLICADO, "0")
        cls.Param.search([("key", "=like", "forum_sagui_support.publicado.%")]).unlink()

    def _filas_de_marcas(self):
        """Todo parámetro del módulo que hable de publicado, con clave vieja o nueva."""
        return self.Param.search_count([("key", "=like", "forum_sagui_support.publicado%")])

    # ================= lo que tiene que seguir haciendo =================
    def test_marca_y_reconoce(self):
        self.assertFalse(self.relay._ya_publicado(10))
        self.relay._marcar_publicado(10)
        self.assertTrue(self.relay._ya_publicado(10))

    def test_todo_lo_anterior_queda_cubierto(self):
        """Es una marca ALTA: marcar el 20 responde por el 19 y por el 1."""
        self.relay._marcar_publicado(20)
        for seq in (1, 7, 19, 20):
            self.assertTrue(self.relay._ya_publicado(seq), "el seq %s quedó sin cubrir" % seq)
        self.assertFalse(self.relay._ya_publicado(21))

    def test_la_marca_NO_baja(self):
        """Un lote desordenado no puede reabrir la puerta a republicar lo ya mostrado."""
        self.relay._marcar_publicado(30)
        self.relay._marcar_publicado(12)          # llega tarde y más bajo
        self.assertTrue(self.relay._ya_publicado(30),
                        "la marca bajó: una respuesta ya leída puede volver a publicarse")
        self.assertEqual(int(self.Param.get_param(self.relay.CLAVE_PUBLICADO)), 30)

    def test_sobrevive_a_un_cursor_retrocedido_a_mano(self):
        """El caso REAL que la marca cubre y el cursor no.

        Alguien retrocede `forum_sagui_support.cursor` para volver a bajar una cola que quedó
        trabada —el README avisa de no tocarlo sin saber por qué, o sea que se toca—. Sagui reenvía
        todo, y lo único que impide que el usuario vea dos veces lo que ya leyó es esta marca, que
        no se mueve con el cursor.
        """
        self.relay._marcar_publicado(50)
        self.Param.set_param("forum_sagui_support.cursor", "0")
        self.assertTrue(self.relay._ya_publicado(50),
                        "con el cursor en cero la marca tiene que seguir tapando el 50")

    # ================= y LO QUE NO PUEDE VOLVER A HACER =================
    def test_mil_mensajes_dejan_UNA_sola_fila(self):
        """El punto de todo el cambio. Antes: 1000 filas para siempre."""
        for seq in range(1, 1001):
            self.relay._marcar_publicado(seq)
        self.assertEqual(
            self._filas_de_marcas(), 1,
            "la dedup volvió a escribir un parámetro por mensaje: %s filas después de 1000 "
            "entregas" % self._filas_de_marcas())
        self.assertTrue(self.relay._ya_publicado(1000))
        self.assertFalse(self.relay._ya_publicado(1001))

    def test_la_clave_no_lleva_el_seq_adentro(self):
        """Garantía estructural: si la clave vuelve a depender del seq, esto lo caza."""
        self.relay._marcar_publicado(777)
        self.assertNotIn("777", self.relay.CLAVE_PUBLICADO)
        self.assertFalse(
            self.Param.search([("key", "like", "%publicado.777")]),
            "volvió a aparecer una clave con el seq adentro")
