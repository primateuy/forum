# -*- coding: utf-8 -*-
"""Aplicación del ajuste de inventario por tandas, por el ORM.

La carga dejó cada quant con su contado (`inventory_quantity_set`). Aplicar es
lo que hace el botón *Aplicar* de Inventario físico: un `stock.move` por quant,
con su valuación y, en categorías con valuación automática, su asiento. Eso no
se hace por SQL: la valuación FIFO, las capas y la contabilidad las resuelve el
ORM (`_apply_inventory`).

Lo que sí se controla acá es el volumen. Aplicar ~900.000 quants desde la
interfaz es una sola transacción de horas. Medido sobre una copia de la base de
prueba ya cargada: ~30 ms por quant (60 s cada tanda de 2.000), y casi todo es
el recompute de `stock.quant.value_report` de tchistorico, que recalcula todos
los quants del producto por cada capa de valuación. Por eso:

- una tanda por corrida del cron, con commit, y `_trigger()` para la siguiente;
- ordenado por ubicación (columna del archivo), para que cada sucursal quede
  bloqueada en un solo tramo;
- si la tanda falla entera, se reintenta quant por quant, cada uno en su
  savepoint, y solo los que fallan quedan como error.

**La diferencia se recalcula al momento de aplicar**, con el quant bloqueado:
la cantidad final queda igual al contado aunque se haya vendido algo entre la
carga y la aplicación. Lo vendido entre el conteo físico y el apply queda
absorbido por el ajuste (limitación documentada en el README).
"""
import logging
import time

from psycopg2.extensions import TransactionRollbackError

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError

from .forum_import_batch_inventario import ACCIONES_QUANT

_logger = logging.getLogger(__name__)

# Pedido de cancelación. Vive fuera de la fila del batch a propósito: ver
# `action_cancelar`.
PARAM_CANCELAR = "forum_partner_import.cancelar_aplicacion.%d"
# Veces que se reintenta una tanda que chocó con otra transacción.
REINTENTOS_TANDA = 3


class ForumImportBatchInventarioApply(models.Model):
    _inherit = "forum.import.batch"

    state = fields.Selection(
        selection_add=[
            ("done",),
            ("applying", "Aplicando ajuste"),
            ("applied", "Ajuste aplicado"),
        ],
        ondelete={"applying": "set default", "applied": "set default"},
    )
    current_phase = fields.Selection(
        [("carga", "Carga"), ("apply", "Aplicación")],
        string="Fase", default="carga", required=True, readonly=True, copy=False,
        help="En qué fase está el batch. Decide qué retoma 'Reanudar' después de "
             "un error o una cancelación.",
    )

    # ------------------------------------------------------------------
    # Configuración de la aplicación
    # ------------------------------------------------------------------
    inventory_accounting_date = fields.Date(
        string="Fecha contable del ajuste",
        help="Fecha de los movimientos de valuación y sus asientos. Vacía: la "
             "fecha en que se aplica. La define el contador del cliente.",
    )
    apply_batch_size = fields.Integer(
        string="Quants por tanda de aplicación", default=2000, required=True,
        help="Cada tanda es una transacción: mientras corre, los quants de la "
             "tanda quedan bloqueados para el POS. Entre 2.000 y 5.000.",
    )

    # ------------------------------------------------------------------
    # Avance de la aplicación
    # ------------------------------------------------------------------
    apply_offset = fields.Integer(string="Puntero de aplicación", readonly=True, copy=False)
    apply_total = fields.Integer(string="Celdas a aplicar", readonly=True, copy=False)
    apply_processed = fields.Integer(string="Celdas revisadas", readonly=True, copy=False)
    applied_count = fields.Integer(
        string="Quants ajustados", readonly=True, copy=False,
        help="Quants con diferencia: cada uno generó su movimiento de inventario.",
    )
    apply_no_diff = fields.Integer(
        string="Sin diferencia", readonly=True, copy=False,
        help="El stock ya era igual al contado: no hace falta movimiento.",
    )
    apply_errors = fields.Integer(string="Errores al aplicar", readonly=True, copy=False)
    apply_started_at = fields.Datetime(string="Inicio de la aplicación", readonly=True, copy=False)
    apply_ended_at = fields.Datetime(string="Fin de la aplicación", readonly=True, copy=False)

    # ==================================================================
    # Despacho desde el modelo base y la carga
    # ==================================================================
    def _valores_reset_carga(self):
        valores = super()._valores_reset_carga()
        valores.update({
            "current_phase": "carga",
            "apply_offset": 0, "apply_total": 0, "apply_processed": 0,
            "applied_count": 0, "apply_no_diff": 0, "apply_errors": 0,
            "apply_started_at": False, "apply_ended_at": False,
        })
        return valores

    def _inv_columnas_export(self):
        return {
            "extra": "apply_resultado AS resultado_aplicacion, apply_error",
            "cond": "OR apply_resultado = 'error'",
        }

    def action_cancelar(self):
        """Mientras se aplica, cancelar es un PEDIDO: se detiene entre tandas.

        No se escribe la fila del batch. La tanda en curso (un minuto o más) la
        escribe al terminar, y dos escrituras concurrentes sobre la misma fila
        hacen fallar su commit con SerializationFailure: se perdía la tanda
        entera y el batch quedaba en error en vez de cancelado. Pasó en la
        prueba. El pedido va a ir.config_parameter y lo lee la corrida
        siguiente del cron, que arranca con una transacción nueva.
        """
        self.ensure_one()
        if self.state != "applying":
            return super().action_cancelar()
        self.env["ir.config_parameter"].sudo().set_param(PARAM_CANCELAR % self.id, "1")
        return self._notificar(
            _("Cancelación pedida"),
            _("La aplicación se detiene al terminar la tanda en curso. Lo ya aplicado queda."))

    def _apl_cancelacion_pedida(self, limpiar=True):
        """¿Pidieron cancelar? Si `limpiar`, además borra el pedido."""
        parametros = self.env["ir.config_parameter"].sudo()
        clave = PARAM_CANCELAR % self.id
        pedida = bool(parametros.get_param(clave))
        if pedida and limpiar:
            parametros.set_param(clave, False)
        return pedida

    def action_reanudar(self):
        self.ensure_one()
        if self.current_phase != "apply":
            return super().action_reanudar()
        if self.state not in ("cancel", "error"):
            raise UserError(_("Solo se reanuda un batch cancelado o con error."))
        self._apl_cancelacion_pedida()   # un pedido viejo no debe frenar la reanudación
        self.write({"state": "applying", "apply_ended_at": False})
        self._log("Aplicación reanudada desde la celda %d." % self.apply_offset)
        self._encolar_cron()
        return True

    def action_drop_staging(self):
        if self.filtered(lambda b: b.state == "applying"):
            raise UserError(_("No se puede borrar el staging mientras se aplica el ajuste."))
        return super().action_drop_staging()

    def unlink(self):
        if self.filtered(lambda b: b.state == "applying"):
            raise UserError(_("No se puede borrar un batch que está aplicando el ajuste."))
        return super().unlink()

    @api.model
    def _cron_procesar(self):
        super()._cron_procesar()
        for batch in self.search([("state", "=", "applying")], order="id"):
            batch._aplicar_varias_tandas()
        return True

    # ==================================================================
    # Arranque
    # ==================================================================
    def action_aplicar_ajuste(self):
        """Valida y deja la aplicación en manos del cron."""
        self.ensure_one()
        if not self._es_inventario():
            raise UserError(_("Solo un ajuste de inventario se aplica."))
        if self.state != "done":
            raise UserError(_("Primero tiene que terminar la carga de quants."))
        if not self._staging_existe():
            raise UserError(_("No existe la tabla staging %s. Volvé a cargarla.")
                            % self._staging_name())
        if self.apply_batch_size < 1:
            raise UserError(_("El tamaño de tanda de aplicación debe ser mayor a cero."))
        if not self.inventory_user_id.has_group("stock.group_stock_manager"):
            raise UserError(_("%s no es administrador de inventario: no puede aplicar "
                              "el ajuste.") % self.inventory_user_id.display_name)

        self._apl_cancelacion_pedida()
        vals = {"state": "applying", "current_phase": "apply", "apply_ended_at": False}
        if not self.apply_started_at:
            # Primera vez: se numeran las celdas a aplicar, por ubicación. El
            # orden queda fijo en staging, así que reanudar retoma exactamente
            # donde quedó aunque se cambie el tamaño de tanda.
            t = self._staging_name()
            self.env.cr.execute("""
                UPDATE {t} s SET apply_seq = r.n, apply_resultado = NULL, apply_error = NULL
                  FROM (SELECT row_num,
                               ROW_NUMBER() OVER (ORDER BY col_excel, fila_excel) AS n
                          FROM {t} WHERE accion_efectiva = ANY(%s)) r
                 WHERE r.row_num = s.row_num
            """.format(t=t), (list(ACCIONES_QUANT),))
            total = self.env.cr.rowcount
            self.env.cr.execute("CREATE INDEX IF NOT EXISTS {t}_apply_idx ON {t} (apply_seq)".format(t=t))
            vals.update({
                "apply_total": total, "apply_offset": 0, "apply_processed": 0,
                "applied_count": 0, "apply_no_diff": 0, "apply_errors": 0,
                "apply_started_at": fields.Datetime.now(),
            })
        self.write(vals)
        self._log("Aplicación iniciada. Celda %d de %d, tandas de %d, fecha contable %s, "
                  "responsable %s."
                  % (self.apply_offset, self.apply_total, self.apply_batch_size,
                     self.inventory_accounting_date or _("la del apply"),
                     self.inventory_user_id.display_name))
        self.env.cr.commit()
        self._encolar_cron()
        # True y no una notificación: el formulario recarga y el widget ve
        # 'applying' (ver la trampa documentada en action_iniciar).
        return True

    # ==================================================================
    # Tandas
    # ==================================================================
    def _aplicar_varias_tandas(self):
        """Una tanda por corrida del cron: cada una ya es una transacción larga."""
        self.ensure_one()
        self.invalidate_recordset(["state", "apply_offset", "apply_total"])
        if self.state != "applying":
            return
        if self._apl_cancelacion_pedida():
            self.write({"state": "cancel", "apply_ended_at": fields.Datetime.now()})
            self._log("Aplicación cancelada por el usuario en la celda %d de %d."
                      % (self.apply_offset, self.apply_total))
            self.env.cr.commit()
            return
        if self.apply_offset >= self.apply_total:
            self._finalizar_aplicacion()
            return
        for intento in range(1, REINTENTOS_TANDA + 1):
            try:
                self._aplicar_tanda()
                self.env.cr.commit()
                break
            except Exception as e:
                self.env.cr.rollback()
                self.env.clear()
                # Un choque de concurrencia (serialización, deadlock) no es un
                # error de datos: la tanda se revirtió entera y se puede repetir.
                if isinstance(e, TransactionRollbackError) and intento < REINTENTOS_TANDA:
                    _logger.warning(
                        "[forum_partner_import][batch %s] la tanda que arranca en %d chocó con "
                        "otra transacción (%s); reintento %d de %d",
                        self.id, self.apply_offset, e, intento + 1, REINTENTOS_TANDA)
                    continue
                self.write({"state": "error", "apply_ended_at": fields.Datetime.now()})
                self._log("ERROR en la tanda de aplicación que arranca en %d: %s"
                          % (self.apply_offset, e))
                self.env.cr.commit()
                _logger.exception("[forum_partner_import] tanda de aplicación fallida")
                return

        self.invalidate_recordset(["apply_offset"])
        if self.apply_offset >= self.apply_total:
            self._finalizar_aplicacion()
            return
        self._encolar_cron()

    def _aplicar_tanda(self):
        """Aplica una tanda de celdas.

        1. Bloquea los quants de la tanda (FOR NO KEY UPDATE). Si el POS está
           tocando alguno, la tanda espera: por eso se corre de noche.
        2. Pone el contado y RECALCULA la diferencia contra la cantidad de ese
           momento (opción "la cantidad final es el contado").
        3. Sin diferencia: se limpia el conteo, no hace falta movimiento.
        4. Con diferencia: `_apply_inventory()` de toda la tanda; si falla, quant
           por quant con savepoint.
        """
        self.ensure_one()
        t0 = time.time()
        desde = self.apply_offset + 1
        hasta = self.apply_offset + self.apply_batch_size
        t = self._staging_name()
        cr = self.env.cr
        Quant = self.env["stock.quant"].with_user(self.inventory_user_id)

        cr.execute("""
            SELECT row_num, product_id, location_id, company_id, cantidad
              FROM {t} WHERE apply_seq BETWEEN %s AND %s ORDER BY apply_seq
        """.format(t=t), (desde, hasta))
        filas = {r[0]: r for r in cr.fetchall()}

        quant_de_fila = self._apl_bloquear_quants(t, desde, hasta)

        resultado, errores = {}, {}
        # Celdas sin quant: con 0 no hay nada que hacer; con contado, el quant
        # desapareció desde la carga (no debería) y se crea por el ORM.
        for row_num, (_r, product_id, location_id, company_id, cantidad) in filas.items():
            if row_num in quant_de_fila:
                continue
            if not cantidad:
                resultado[row_num] = "sin_diferencia"
                continue
            try:
                with cr.savepoint():
                    quant = Quant.with_company(company_id).with_context(inventory_mode=True).create({
                        "product_id": product_id, "location_id": location_id,
                        "inventory_quantity": float(cantidad),
                    })
                quant_de_fila[row_num] = quant.id
            except Exception as e:
                resultado[row_num] = "error"
                errores[row_num] = tools.ustr(e)[:1000]

        con_diferencia = self._apl_poner_contado(t, quant_de_fila, resultado)
        self.env["stock.quant"].invalidate_model()

        # Con diferencia: por compañía, porque el ORM valúa con la compañía
        # del entorno.
        por_compania = {}
        for row_num, quant_id in con_diferencia.items():
            por_compania.setdefault(filas[row_num][3], []).append((row_num, quant_id))
        for company_id, pares in por_compania.items():
            ok, fallidos = self._apl_aplicar(Quant.with_company(company_id), pares)
            for row_num in ok:
                resultado[row_num] = "aplicado"
            for row_num, mensaje in fallidos.items():
                resultado[row_num] = "error"
                errores[row_num] = mensaje

        # Registro por celda en staging.
        if resultado:
            filas_res = list(resultado)
            cr.execute("""
                UPDATE {t} s SET apply_resultado = m.res, apply_error = m.err
                  FROM unnest(%s::bigint[], %s::varchar[], %s::text[]) AS m(row_num, res, err)
                 WHERE s.row_num = m.row_num
            """.format(t=t), (filas_res, [resultado[r] for r in filas_res],
                              [errores.get(r) for r in filas_res]))

        valores = list(resultado.values())
        aplicados = valores.count("aplicado")
        sin_dif = valores.count("sin_diferencia")
        con_error = valores.count("error")
        self.write({
            "apply_offset": min(hasta, self.apply_total),
            "apply_processed": self.apply_processed + len(filas),
            "applied_count": self.applied_count + aplicados,
            "apply_no_diff": self.apply_no_diff + sin_dif,
            "apply_errors": self.apply_errors + con_error,
        })
        _logger.info(
            "[forum_partner_import][batch %s] aplicación %d-%d en %.1fs | ajustados=%d "
            "sin_diferencia=%d errores=%d",
            self.id, desde, min(hasta, self.apply_total), time.time() - t0,
            aplicados, sin_dif, con_error)

    def _apl_bloquear_quants(self, t, desde, hasta):
        """{row_num: quant_id} de la tanda, con los quants bloqueados.

        Si un par tiene más de un quant (lo puede dejar el core cuando dos
        transacciones chocan), se fusionan con el método del core antes de
        seguir: ajustar uno solo dejaría el total distinto del contado.
        """
        cr = self.env.cr
        consulta = """
            SELECT s.row_num, q.id
              FROM {t} s
              JOIN stock_quant q ON q.product_id = s.product_id AND q.location_id = s.location_id
             WHERE s.apply_seq BETWEEN %s AND %s
               AND q.lot_id IS NULL AND q.package_id IS NULL AND q.owner_id IS NULL
             ORDER BY q.id
               FOR NO KEY UPDATE OF q
        """.format(t=t)
        cr.execute(consulta, (desde, hasta))
        pares = cr.fetchall()
        vistos = {}
        for row_num, quant_id in pares:
            vistos.setdefault(row_num, []).append(quant_id)
        duplicados = [q for ids in vistos.values() if len(ids) > 1 for q in ids]
        if duplicados:
            self.env["stock.quant"].sudo().browse(duplicados)._merge_quants()
            cr.execute(consulta, (desde, hasta))
            vistos = {}
            for row_num, quant_id in cr.fetchall():
                vistos.setdefault(row_num, []).append(quant_id)
        # Si después de fusionar sigue habiendo más de uno, se toma el menor:
        # _merge_quants deja siempre el de id más chico.
        return {row_num: min(ids) for row_num, ids in vistos.items()}

    def _apl_poner_contado(self, t, quant_de_fila, resultado):
        """Pone el contado recalculando la diferencia. Devuelve los que tienen diferencia.

        Los que no tienen diferencia se limpian acá mismo (el conteo coincide con
        el stock) y quedan en `resultado` como 'sin_diferencia'.
        """
        if not quant_de_fila:
            return {}
        cr = self.env.cr
        filas_q = list(quant_de_fila)
        tiene_reason = "reason" in self.env["stock.quant"]._fields
        cr.execute("""
            WITH m AS (
                SELECT * FROM unnest(%(filas)s::bigint[], %(quants)s::int[]) AS m(row_num, quant_id)
            )
            UPDATE stock_quant q SET
                inventory_quantity = s.cantidad,
                inventory_diff_quantity = s.cantidad - coalesce(q.quantity, 0),
                inventory_quantity_set = true,
                user_id = %(usuario)s,
                accounting_date = %(fecha)s,
                write_uid = %(uid)s,
                write_date = now() AT TIME ZONE 'UTC'
                {reason}
              FROM m JOIN {t} s ON s.row_num = m.row_num
             WHERE q.id = m.quant_id
            RETURNING m.row_num, q.id,
                      abs(q.inventory_diff_quantity) < (
                          SELECT u.rounding / 2 FROM product_product pp
                            JOIN product_template pt ON pt.id = pp.product_tmpl_id
                            JOIN uom_uom u ON u.id = pt.uom_id
                           WHERE pp.id = q.product_id) AS sin_diferencia
        """.format(t=t, reason=", reason = %(reason)s" if tiene_reason else ""), {
            "filas": filas_q, "quants": [quant_de_fila[r] for r in filas_q],
            "usuario": self.inventory_user_id.id, "uid": self.env.uid,
            "fecha": self.inventory_accounting_date or None,
            "reason": self.inventory_reason,
        })
        con_diferencia, limpiar = {}, []
        for row_num, quant_id, sin_diferencia in cr.fetchall():
            if sin_diferencia:
                resultado[row_num] = "sin_diferencia"
                limpiar.append(quant_id)
            else:
                con_diferencia[row_num] = quant_id
        if limpiar:
            # Lo mismo que action_clear_inventory_quantity, sin pasar por el ORM.
            cr.execute("""
                UPDATE stock_quant SET inventory_quantity = 0, inventory_diff_quantity = 0,
                       inventory_quantity_set = false, user_id = NULL, accounting_date = NULL
                       {reason}
                 WHERE id = ANY(%s)
            """.format(reason=", reason = NULL" if tiene_reason else ""), (limpiar,))
        return con_diferencia

    def _apl_aplicar(self, Quant, pares):
        """`_apply_inventory` de la tanda; si falla, uno por uno.

        Devuelve (filas aplicadas, {fila: mensaje de error}).
        """
        cr = self.env.cr
        ids = [quant_id for _r, quant_id in pares]
        try:
            with cr.savepoint():
                Quant.browse(ids)._apply_inventory()
            return [row_num for row_num, _q in pares], {}
        except Exception as e:
            _logger.warning("[forum_partner_import][batch %s] tanda de %d quants falló (%s); "
                            "se reintenta uno por uno", self.id, len(ids), e)

        ok, fallidos = [], {}
        for row_num, quant_id in pares:
            try:
                with cr.savepoint():
                    Quant.browse(quant_id)._apply_inventory()
                ok.append(row_num)
            except Exception as e:
                fallidos[row_num] = tools.ustr(e)[:1000]
        return ok, fallidos

    def _finalizar_aplicacion(self):
        self.ensure_one()
        self.write({"state": "applied", "apply_ended_at": fields.Datetime.now()})
        self.env.registry.clear_cache()
        self._log("Ajuste aplicado. Quants ajustados=%d Sin diferencia=%d Errores=%d."
                  % (self.applied_count, self.apply_no_diff, self.apply_errors))
        if self.apply_errors:
            self._log("Los quants con error conservan su conteo en Inventario físico y la "
                      "tabla staging %s tiene el motivo de cada uno." % self._staging_name())
        self.env.cr.commit()
