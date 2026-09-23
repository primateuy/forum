# -*- coding: utf-8 -*-
# El orden del guion: un paso inalcanzable es válido en datos, pero moverlo mal cambia el flujo
# para todos los visitantes. Un test por cada camino que produce el orden roto.
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "forum_sagui")
class TestOrdenDelGuion(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.guion = cls.env.ref("forum_sagui_support.chatbot_script_sagui")
        cls.conversacion = cls.env.ref("forum_sagui_support.step_sagui_consulta")
        cls.forward = cls.env.ref("forum_sagui_support.step_sagui_operador")
        cls.bienvenida = cls.env.ref("forum_sagui_support.step_sagui_bienvenida")
        cls.correo = cls.env.ref("forum_sagui_support.step_sagui_correo")

    def test_el_guion_nace_en_orden(self):
        self.assertLess(self.conversacion.sequence, self.forward.sequence)

    # ------------------------------------------------------------------
    def test_mover_el_forward_antes_de_la_conversacion(self):
        with self.assertRaises(ValidationError):
            self.forward.sequence = self.conversacion.sequence - 1
            self.env.flush_all()

    def test_mover_la_conversacion_despues_del_forward(self):
        """El camino inverso: produce el MISMO flujo roto sin tocar el registro del forward.

        Una constraint que sólo mire el paso forward no lo ve nunca.
        """
        with self.assertRaises(ValidationError):
            self.conversacion.sequence = self.forward.sequence + 1
            self.env.flush_all()

    def test_write_en_lote_como_la_manija_de_arrastre(self):
        """El editor reescribe `sequence` sobre varios pasos de una vez.

        Validar registro por registro, aislado, no ve el estado final del conjunto.
        """
        pasos = self.bienvenida | self.correo | self.forward | self.conversacion
        with self.assertRaises(ValidationError):
            for paso, seq in zip(pasos, (1, 2, 3, 4)):
                # forward=3, conversación=4 -> el orden queda roto, pero ningún write aislado
                # "mueve el forward antes de la conversación" mirado por sí solo
                paso.sequence = seq
            self.env.flush_all()

    def test_misma_secuencia_tambien_se_rechaza(self):
        """Dos pasos con la misma secuencia dejan el orden a merced del id: no está definido."""
        with self.assertRaises(ValidationError):
            self.forward.sequence = self.conversacion.sequence
            self.env.flush_all()

    # ------------------------------------------------------------------
    def test_reordenar_lo_demas_no_molesta(self):
        """Mover los pasos que no participan de la relación tiene que pasar sin ruido."""
        self.bienvenida.sequence = 2
        self.correo.sequence = 1
        self.env.flush_all()
        self.assertEqual(self.correo.sequence, 1)
        self.assertLess(self.conversacion.sequence, self.forward.sequence)

    def test_alejar_el_forward_esta_permitido(self):
        self.forward.sequence = 99
        self.env.flush_all()
        self.assertEqual(self.forward.sequence, 99)

    # ------------------------------------------------------------------
    # Guardas de conjunto vacío. La constraint valida el orden ENTRE dos pasos: si falta
    # cualquiera de los dos, no hay orden que validar y tiene que dejar trabajar. Sin la guarda,
    # `min()` sobre un recordset vacío levanta ValueError y el admin no puede ni tocar una
    # secuencia. Estos tests existen para que un refactor no se lleve la guarda por delante.
    def test_sin_paso_forward_se_puede_reordenar(self):
        """El admin borró el pase a operador. Pierde el traspaso en vivo —hay un aviso en el log
        para eso— pero no puede quedar impedido de editar el resto del guion."""
        self.forward.unlink()
        self.bienvenida.sequence = 5
        self.env.flush_all()
        self.assertEqual(self.bienvenida.sequence, 5)

    def test_sin_paso_de_conversacion_se_puede_reordenar(self):
        """Guion a medio armar: tampoco hay relación que validar."""
        self.conversacion.unlink()
        self.forward.sequence = 1
        self.env.flush_all()
        self.assertEqual(self.forward.sequence, 1)

    def test_otro_guion_no_se_toca(self):
        """La regla es de ESTE guion; otros chatbots del cliente no son asunto del módulo."""
        otro = self.env["chatbot.script"].create({"title": "Guion ajeno"})
        pasos = self.env["chatbot.script.step"].create([
            {"chatbot_script_id": otro.id, "sequence": 1, "step_type": "forward_operator",
             "message": "op"},
            {"chatbot_script_id": otro.id, "sequence": 2, "step_type": "free_input_multi",
             "message": "hablá"},
        ])
        self.env.flush_all()
        self.assertEqual(len(pasos), 2, "en otro guion, el orden lo decide su dueño")
