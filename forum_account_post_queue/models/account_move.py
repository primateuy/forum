import logging
import threading

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# Tope de lineas por tanda. Se cuenta en lineas de factura (las mismas que mira
# el punto de emision), no en apuntes contables, para que el numero signifique
# lo mismo que el "Cantidad maxima de lineas" que el usuario ya conoce.
PARAM_MAX_LINEAS = "forum.post_queue_max_lines"
# A partir de cuantas facturas seleccionadas se encola en vez de registrar en el
# momento. Con 2, seleccionar una sola sigue registrando al instante.
PARAM_MIN_FACTURAS = "forum.post_queue_min_moves"
# Tope de lineas por corrida del cron, para no pasarse del limit_time_real. Si
# queda cola, el cron se auto-dispara y sigue enseguida.
PARAM_MAX_LINEAS_CORRIDA = "forum.post_queue_max_lines_per_run"

DEFAULT_MAX_LINEAS = 199
DEFAULT_MIN_FACTURAS = 2
DEFAULT_MAX_LINEAS_CORRIDA = 3000

CRON_XMLID = "forum_account_post_queue.ir_cron_post_queued"


class AccountMove(models.Model):
    _inherit = "account.move"

    forum_post_queue_state = fields.Selection(
        selection=[("queued", "En cola"), ("error", "Error al registrar")],
        string="Cola de registro",
        copy=False,
        index=True,
        readonly=True,
        help="Marca de la cola de registro en segundo plano. Vacio = la factura "
             "no esta en la cola.",
    )
    forum_post_queue_error = fields.Text(
        string="Motivo del error",
        copy=False,
        readonly=True,
        help="Motivo por el que el cron no pudo registrar esta factura.",
    )
    forum_post_queue_uid = fields.Many2one(
        comodel_name="res.users",
        string="Encolada por",
        ondelete="set null",
        copy=False,
        readonly=True,
        index=True,
        help="Usuario que pidio el registro. El cron registra en su nombre para "
             "que las reglas de acceso y el chatter queden igual que si lo "
             "hubiera hecho el mismo.",
    )
    forum_post_queue_date = fields.Datetime(
        string="Encolada el", copy=False, readonly=True,
    )
    forum_post_queue_force = fields.Boolean(
        string="Forzar registro",
        copy=False,
        readonly=True,
        help="Equivalente al check 'Forzar' del asistente de registro: registra "
             "tambien las que tienen fecha futura, en vez de dejarlas para su fecha.",
    )

    # === Parametros =======================================================

    @api.model
    def _forum_queue_param(self, clave, defecto):
        """Lee un entero positivo de ir.config_parameter, con defecto si no sirve."""
        valor = self.env["ir.config_parameter"].sudo().get_param(clave)
        try:
            valor = int(valor)
        except (TypeError, ValueError):
            return defecto
        return valor if valor > 0 else defecto

    def _forum_queue_lineas(self):
        """Cantidad de lineas con la que esta factura pesa en la tanda.

        Se cuentan las lineas de factura, que es la unidad del tope del punto de
        emision. Para un asiento contable comun, que no tiene lineas de factura,
        se cuentan los apuntes.
        """
        self.ensure_one()
        return len(self.invoice_line_ids) or len(self.line_ids)

    # === Escritura de los campos de la cola ===============================

    def _forum_write_cola(self, vals):
        """Escribe los campos de la cola sin disparar el recalculo de la factura.

        Escribir cualquier cosa en una factura en borrador hace que Odoo
        reconstruya sus lineas dinamicas (impuestos, descuentos, plazos de
        pago). Sobre un lote grande eso dispara el mismo `RecursionError` del
        core que impide registrar en lote: `discount_allocation_dirty` no esta
        almacenado, su compute escribe, la escritura lo vuelve a leer, y la
        recursion crece con la cantidad de lineas del lote.

        Los campos de la cola no participan de ninguna linea dinamica, asi que
        saltear el recalculo con `skip_invoice_sync` -la misma llave que usa el
        core en `_sync_dynamic_lines`- es exacto, no un atajo.
        """
        return self.with_context(skip_invoice_sync=True).write(vals)

    # === Encolado =========================================================

    def _forum_enqueue_post(self, force_post=False):
        """Marca los borradores para que el cron los registre. Devuelve los marcados."""
        candidatos = self.filtered(lambda m: m.state == "draft")
        if not candidatos:
            return candidatos
        candidatos._forum_write_cola({
            "forum_post_queue_state": "queued",
            "forum_post_queue_error": False,
            "forum_post_queue_uid": self.env.uid,
            "forum_post_queue_date": fields.Datetime.now(),
            "forum_post_queue_force": force_post,
        })
        _logger.info(
            "[cola de registro] %s facturas encoladas por %s: %s",
            len(candidatos), self.env.user.login, candidatos.ids,
        )
        self._forum_disparar_cron()
        return candidatos

    @api.model
    def _forum_disparar_cron(self):
        """Pide que el cron corra en la proxima vuelta del planificador."""
        cron = self.env.ref(CRON_XMLID, raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    def action_forum_dequeue(self):
        """Saca las facturas de la cola sin registrarlas."""
        self._forum_write_cola(
            {"forum_post_queue_state": False, "forum_post_queue_error": False}
        )
        return True

    def action_forum_requeue(self):
        """Vuelve a poner en cola las que quedaron con error."""
        for move in self.filtered(lambda m: m.state == "draft"):
            move._forum_enqueue_post(force_post=move.forum_post_queue_force)
        return True

    # === Limpieza de la marca =============================================

    def _post(self, soft=True):
        """Registrar una factura la saca de la cola, la postee el cron o el usuario."""
        registradas = super()._post(soft=soft)
        encoladas = registradas.filtered("forum_post_queue_state")
        if encoladas:
            encoladas._forum_write_cola({
                "forum_post_queue_state": False,
                "forum_post_queue_error": False,
            })
        return registradas

    def button_cancel(self):
        res = super().button_cancel()
        encoladas = self.filtered("forum_post_queue_state")
        if encoladas:
            encoladas._forum_write_cola({
                "forum_post_queue_state": False,
                "forum_post_queue_error": False,
            })
        return res

    # === Armado de tandas =================================================

    @api.model
    def _forum_armar_tandas(self, moves, max_lineas):
        """Reparte las facturas en tandas que no pasen el tope de lineas.

        Primero separa por compania, por usuario que encolo y por el flag de
        forzado, porque cada tanda se registra con esa compania y ese usuario y
        mezclarlos daria un registro con el contexto equivocado.

        Dentro de cada grupo acumula hasta el tope. Una factura que por si sola
        ya lo supere va sola en su tanda: no se parte nunca una factura.

        :return: lista de (recordset, cantidad_de_lineas)
        """
        grupos = {}
        for move in moves:
            clave = (
                move.company_id.id,
                move.forum_post_queue_uid.id,
                move.forum_post_queue_force,
            )
            grupos.setdefault(clave, []).append(move)

        tandas = []
        for miembros in grupos.values():
            actual = self.browse()
            lineas = 0
            for move in miembros:
                n = move._forum_queue_lineas()
                if actual and lineas + n > max_lineas:
                    tandas.append((actual, lineas))
                    actual = self.browse()
                    lineas = 0
                actual |= move
                lineas += n
            if actual:
                tandas.append((actual, lineas))
        return tandas

    # === Registro =========================================================

    @api.model
    def _forum_post_moves(self, moves):
        """Registra una tanda con la compania y el usuario que la encolaron.

        El contexto `validate_analytic` replica el que manda el boton del
        asistente de registro, para que el cron valide lo mismo que validaria el
        usuario registrando a mano.
        """
        referencia = moves[0]
        destino = moves.with_company(referencia.company_id).with_context(
            validate_analytic=True,
        )
        usuario = referencia.forum_post_queue_uid
        if usuario and usuario.active and usuario.id != self.env.uid:
            destino = destino.with_user(usuario)
        destino._post(soft=not referencia.forum_post_queue_force)

    @api.model
    def _forum_marcar_error(self, moves, error):
        """Deja la factura fuera de la cola, marcada, con el motivo a la vista."""
        motivo = str(error) or error.__class__.__name__
        moves.sudo()._forum_write_cola({
            "forum_post_queue_state": "error",
            "forum_post_queue_error": motivo,
        })
        for move in moves:
            move.sudo().message_post(
                body=_("No se pudo registrar automaticamente: %s", motivo),
                message_type="comment",
            )

    @api.model
    def _forum_post_tanda(self, tanda):
        """Registra una tanda; si falla, reintenta de a una y marca las que fallen.

        Commitea al terminar: lo que se registro queda guardado aunque una tanda
        posterior falle, y recien ahi corre el hook de postcommit que emite el
        CFE. Sin el commit, un error mas adelante volteria facturas ya emitidas.
        """
        try:
            with self.env.cr.savepoint():
                self._forum_post_moves(tanda)
        except Exception:
            _logger.warning(
                "[cola de registro] fallo la tanda %s, reintento de a una",
                tanda.ids, exc_info=True,
            )
            for move in tanda:
                try:
                    with self.env.cr.savepoint():
                        self._forum_post_moves(move)
                except Exception as error:  # noqa: BLE001 - el cron no puede caerse
                    _logger.warning(
                        "[cola de registro] la factura %s quedo con error",
                        move.id, exc_info=True,
                    )
                    self._forum_marcar_error(move, error)

        tanda.invalidate_recordset()
        self._forum_diferidas(tanda)
        ok = tanda.filtered(lambda m: m.state == "posted")
        self._forum_commit()
        return ok

    @api.model
    def _forum_diferidas(self, tanda):
        """Saca de la cola las que Odoo dejo programadas para su fecha.

        Sin forzar, `_post` no registra las facturas con fecha futura: las deja
        en borrador con `auto_post` para que el cron del core las tome el dia que
        corresponde. Si las dejaramos marcadas, nuestra cola las volveria a
        tomar cada 10 minutos para siempre.
        """
        diferidas = tanda.filtered(
            lambda m: m.state == "draft" and m.forum_post_queue_state == "queued"
        )
        if not diferidas:
            return
        diferidas.sudo()._forum_write_cola({"forum_post_queue_state": False})
        for move in diferidas:
            move.sudo().message_post(
                body=_(
                    "Queda programada para registrarse sola el %s, por tener fecha "
                    "futura. Se saca de la cola de registro.",
                    move.date,
                ),
                message_type="comment",
            )

    @api.model
    def _forum_commit(self):
        """Commitea, salvo en tests, donde romperia los savepoints de la prueba.

        Se mira el flag `testing` del hilo ademas del modo de test del registry:
        es el mismo par de condiciones que usa el core para decidir si puede
        commitear (ver `ir_mail_server._is_test_mode`), y el unico que cubre un
        `TransactionCase` comun.
        """
        en_test = getattr(threading.current_thread(), "testing", False)
        if en_test or self.env.registry.in_test_mode():
            return
        self.env.cr.commit()  # pylint: disable=invalid-commit

    # === Cron =============================================================

    @api.model
    def _forum_cron_post_queued(self):
        """Registra las facturas en cola, de a tandas, en orden de fecha.

        El orden por fecha importa: la numeracion y la secuencia de CFE se
        asignan al registrar, asi que registrar desordenado dejaria los numeros
        desordenados respecto de las fechas.
        """
        max_lineas = self._forum_queue_param(PARAM_MAX_LINEAS, DEFAULT_MAX_LINEAS)
        tope_corrida = self._forum_queue_param(
            PARAM_MAX_LINEAS_CORRIDA, DEFAULT_MAX_LINEAS_CORRIDA
        )

        pendientes = self.search(
            [("forum_post_queue_state", "=", "queued"), ("state", "=", "draft")],
            order="date, id",
        )
        if not pendientes:
            return

        tandas = self._forum_armar_tandas(pendientes, max_lineas)
        _logger.info(
            "[cola de registro] %s facturas pendientes en %s tandas (tope %s lineas)",
            len(pendientes), len(tandas), max_lineas,
        )

        registradas = 0
        lineas_corrida = 0
        for tanda, lineas in tandas:
            ok = self._forum_post_tanda(tanda)
            registradas += len(ok)
            lineas_corrida += lineas
            if lineas_corrida >= tope_corrida:
                _logger.info(
                    "[cola de registro] corte por tope de corrida (%s lineas)",
                    lineas_corrida,
                )
                break

        quedan = self.search_count(
            [("forum_post_queue_state", "=", "queued"), ("state", "=", "draft")]
        )
        _logger.info(
            "[cola de registro] registradas %s, quedan %s en cola", registradas, quedan
        )
        if quedan:
            self._forum_disparar_cron()
