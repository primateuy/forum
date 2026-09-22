# -*- coding: utf-8 -*-
"""Aplicación del ajuste de inventario por tandas: SQL set-based con un híbrido ORM.

Aplicar ~900.000 quants por el ORM (`_apply_inventory`) tarda horas: ~30 ms por
quant, casi todo recompute de tchistorico. Acá la aplicación va por SQL,
replicando campo por campo lo que hace el ORM. La réplica sale de una disección
de `_apply_inventory` sobre cada caso (alta, suba, baja con consumo FIFO, quant
negativo, contado 0, diferencia 0, reserva, producto con costo, capa negativa)
y se valida con una prueba de paridad contra el ORM (ver README).

Lo que hace el ORM por quant, y replica `_apl_sql`:

- `stock.move` + `stock.move.line` en `done`. Con diferencia 0 igual crea un
  movimiento de cantidad 0 ("Product Quantity Confirmed").
- Diferencia > 0: ubicación de ajuste → existencias; si no, al revés.
- Quant contado: `quantity += diferencia`, conteo limpio, `inventory_date` =
  próxima fecha de inventario de la ubicación, `reason` en NULL. `in_date`: en
  una entrada queda el más viejo entre el suyo (si tenía stock) y ahora; en una
  salida queda el suyo (si tenía stock) o ahora.
- Quant de la ubicación de ajuste: `quantity -= diferencia`; su `in_date` es el
  de la última línea del producto (ahora en una entrada, el `in_date` del origen
  en una salida). Si no existe se crea.
- `stock.valuation.layer` por cada movimiento con cantidad: primero todas las
  entradas y después las salidas, que consumen FIFO las capas con saldo
  (`create_date, id`), incluidas las entradas recién creadas.
- `last_inventory_date` de la ubicación.
- Cascadas de módulos (una sola vez al final, `_apl_recalculos_finales`):
  `value_report` de tchistorico en todos los quants del producto,
  `ultimo_costo_mr` del producto y la plantilla, `qty_to_order` de los puntos
  de reorden.

**Híbrido.** Un producto va por el ORM, con todas sus celdas de la tanda, si
algo de su valuación no es cero o hay efectos que el SQL no replica: costo,
capas con valor, capas negativas (vacuum), reservas o líneas pendientes en la
ubicación, costo que no sea FIFO, seguimiento por lote, par sin quant o con
quants duplicados. Como FIFO se lleva por producto, los dos caminos nunca
comparten estado. Nada de asientos contables por SQL.

**La diferencia se recalcula al momento de aplicar**, con la tabla de quants
bloqueada: la cantidad final queda igual al contado aunque se haya vendido algo
entre la carga y la aplicación (limitación documentada en el README).
"""
import logging
import time

from psycopg2.extensions import TransactionRollbackError

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError

from .forum_import_batch_inventario import ACCIONES_QUANT

_logger = logging.getLogger(__name__)

# Pedido de cancelación. Vive fuera de la fila del batch a propósito: ver
# `action_cancelar`. El mismo mecanismo sirve para la fase de publicación.
PARAM_CANCELAR = "forum_partner_import.cancelar_aplicacion.%d"
# Veces que se reintenta una tanda que chocó con otra transacción.
REINTENTOS_TANDA = 3
# Productos por tramo en los recálculos finales (cada tramo hace commit).
PASO_RECALCULO = 2000

# Campos de tchistorico en stock.valuation.layer y el valor que su create()
# pone cuando la capa vale 0 (rama `else` de su override). `unit_cost_report`
# es un calculado: unit_cost * (cotizacionDia or 1) = 0.
SVL_TCHISTORICO_CERO = ("cotizacionDia", "valorMonedaSecundaria", "valorRestante",
                        "valorUnitario", "ucmr", "unit_cost_report")

# Campos de tchistorico que su create() calcula cuando la capa SÍ tiene valor.
# Se replican a mano porque el INSERT por SQL no pasa por ese create(): ver
# `_apl_tchistorico`. El orden no importa; la lista sí, para no olvidarse uno.
SVL_TCHISTORICO_CON_VALOR = ("cotizacionDia", "valorMonedaSecundaria", "valorRestante",
                             "valorUnitario", "moneda_reporte_id", "unitCostesDestinoInc",
                             "unitCostesDestinoIncMR", "valorizadoCosteDestino",
                             "valorizadoCosteDestinoMR", "ucmr", "unit_cost_report")

# --- Publicación de los asientos (fase 3) -----------------------------------
# Asientos por tanda. Medido sobre la tabla LLENA (817.007 borradores, 1,66 M de
# líneas), que es el escenario real: 150→15,05 ms por asiento, 500→13,82,
# 1.000→14,28, 2.000→14,21. La curva es casi PLANA y 500 es el mejor.
#
# Sobre una tabla con 200 asientos la misma medición daba 4,95 ms y parecía que
# agrandar la tanda empeoraba; a escala eso no se sostiene. Lo que domina es el
# `action_post` en sí (12,4 ms de los 14,9), no el tamaño del lote: la
# numeración del diario pesa los otros 2,5 ms. **Si se vuelve a medir, tiene que
# ser con la tabla en volumen real.**
LOTE_PUBLICACION = 500
# Veces que se reintenta un asiento suelto que falló al publicar.
REINTENTOS_ASIENTO = 2

# --- Guard del WMS ----------------------------------------------------------
# `integracion_wis` engancha `write` de product.product y product.template y, si
# la comunicación está activa, hace un request HTTP por producto. El apply por
# ORM lo dispara por DOS vías: `_run_fifo` escribe `standard_price` del producto,
# y mover stock reactiva pickings en espera (`_action_assign` → insertarPedidos).
# Este contexto es el guard que el propio módulo respeta. Va en TODOS los
# caminos ORM de la aplicación. Ver el README (riesgos de producción).
CONTEXTO_SIN_WMS = {"_avoid_wms": True, "skip_wms_integration": True}
# Tablas donde `integracion_wis` registra lo que SALE hacia el WMS. La fase de
# invariantes exige delta 0 en las tres: si alguna creció, algo se escapó del
# guard. Las de entrada (wis_webhook_log, wms_pedido_evento) no se auditan.
TABLAS_WMS_SALIENTES = ("product_wms_log", "wis_sync_queue", "wms_integracion_log")


class ForumImportBatchInventarioApply(models.Model):
    _inherit = "forum.import.batch"

    state = fields.Selection(
        selection_add=[
            ("done",),
            ("applying", "Aplicando ajuste"),
            ("applied", "Ajuste aplicado"),
            ("posting", "Publicando asientos"),
            ("posted", "Asientos publicados"),
        ],
        ondelete={"applying": "set default", "applied": "set default",
                  "posting": "set default", "posted": "set default"},
    )
    current_phase = fields.Selection(
        [("carga", "Carga"), ("apply", "Aplicación"), ("post", "Publicación")],
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
        string="Celdas por tanda de aplicación", default=50000, required=True,
        help="Cada tanda es una transacción con la tabla de quants bloqueada.",
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
        help="El stock ya era igual al contado. Si hay quant, igual queda un "
             "movimiento de cantidad 0, como hace Odoo.",
    )
    apply_via_orm = fields.Integer(
        string="Celdas vía ORM", readonly=True, copy=False,
        help="Celdas de productos con valuación distinta de cero o con reservas: "
             "se aplican con _apply_inventory.",
    )
    apply_errors = fields.Integer(string="Errores al aplicar", readonly=True, copy=False)
    apply_layers_valued = fields.Integer(
        string="Capas con valor", readonly=True, copy=False,
        help="Capas de valuación con valor distinto de cero creadas por la "
             "aplicación. Cada una genera un asiento.",
    )
    apply_entries = fields.Integer(
        string="Asientos en borrador", readonly=True, copy=False,
        help="Asientos de valuación que la aplicación creó en borrador. Los "
             "publica la fase 3 por el ORM, que asigna la numeración del diario.",
    )
    apply_step = fields.Char(string="Etapa de la aplicación", readonly=True, copy=False)
    apply_started_at = fields.Datetime(string="Inicio de la aplicación", readonly=True, copy=False)
    apply_ended_at = fields.Datetime(string="Fin de la aplicación", readonly=True, copy=False)

    # ------------------------------------------------------------------
    # Fase 3: publicación de los asientos (por ORM, a propósito)
    # ------------------------------------------------------------------
    post_batch_size = fields.Integer(
        string="Asientos por tanda de publicación", default=LOTE_PUBLICACION, required=True,
        help="Con la tabla de asientos LLENA el costo por asiento es casi plano "
             "entre 150 y 2.000: medido sobre 817.007 borradores, 150→15,05 ms, "
             "500→13,82, 1.000→14,28, 2.000→14,21. El default 500 es el mejor "
             "medido, y lo que domina no es el tamaño de la tanda sino el "
             "action_post en sí (12,4 ms de los 14,9; la numeración del diario "
             "pesa los otros 2,5). Sobre una tabla vacía daba 4,95 ms y ese "
             "número NO se sostiene a escala: si se vuelve a medir, hacerlo con "
             "la tabla en volumen real.",
    )
    post_total = fields.Integer(string="Asientos a publicar", readonly=True, copy=False)
    post_done = fields.Integer(string="Asientos publicados", readonly=True, copy=False)
    post_errors = fields.Integer(string="Asientos con error", readonly=True, copy=False)
    post_step = fields.Char(string="Etapa de la publicación", readonly=True, copy=False)
    post_started_at = fields.Datetime(string="Inicio de la publicación", readonly=True, copy=False)
    post_ended_at = fields.Datetime(string="Fin de la publicación", readonly=True, copy=False)

    # ------------------------------------------------------------------
    # Verificación por invariantes
    # ------------------------------------------------------------------
    check_state = fields.Selection(
        [("pendiente", "Pendiente"), ("ok", "Todo verde"), ("fallo", "Con violaciones")],
        string="Verificación", default="pendiente", readonly=True, copy=False,
        help="Resultado del set de invariantes que se corre sobre el 100% de lo "
             "generado, al terminar la aplicación y otra vez al terminar la "
             "publicación.",
    )
    check_report = fields.Text(
        string="Informe de invariantes", readonly=True, copy=False,
        help="Una línea por invariante, con el número de violaciones y el detalle.",
    )
    check_at = fields.Datetime(string="Última verificación", readonly=True, copy=False)

    # ==================================================================
    # Despacho desde el modelo base y la carga
    # ==================================================================
    def _valores_reset_carga(self):
        valores = super()._valores_reset_carga()
        valores.update({
            "current_phase": "carga",
            "apply_offset": 0, "apply_total": 0, "apply_processed": 0,
            "applied_count": 0, "apply_no_diff": 0, "apply_errors": 0,
            "apply_via_orm": 0, "apply_step": False,
            "apply_layers_valued": 0, "apply_entries": 0,
            "apply_started_at": False, "apply_ended_at": False,
            "post_total": 0, "post_done": 0, "post_errors": 0, "post_step": False,
            "post_started_at": False, "post_ended_at": False,
            "check_state": "pendiente", "check_report": False, "check_at": False,
        })
        return valores

    def _inv_columnas_export(self):
        return {
            "extra": "apply_resultado AS resultado_aplicacion, apply_error",
            "cond": "OR apply_resultado = 'error'",
        }

    def action_cancelar(self):
        """Mientras se aplica o se publica, cancelar es un PEDIDO.

        No se escribe la fila del batch. La tanda en curso la escribe al
        terminar, y dos escrituras concurrentes sobre la misma fila hacen fallar
        su commit con SerializationFailure: se perdía la tanda entera y el batch
        quedaba en error en vez de cancelado. El pedido va a ir.config_parameter
        y lo lee la corrida siguiente del cron, que arranca con otra transacción.
        """
        self.ensure_one()
        if self.state not in ("applying", "posting"):
            return super().action_cancelar()
        self.env["ir.config_parameter"].sudo().set_param(PARAM_CANCELAR % self.id, "1")
        if self.state == "posting":
            return self._notificar(
                _("Cancelación pedida"),
                _("La publicación se detiene al terminar la tanda en curso. Los asientos "
                  "ya publicados quedan publicados; el resto sigue en borrador."))
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
        if self.current_phase not in ("apply", "post"):
            return super().action_reanudar()
        if self.state not in ("cancel", "error"):
            raise UserError(_("Solo se reanuda un batch cancelado o con error."))
        self._apl_cancelacion_pedida()   # un pedido viejo no debe frenar la reanudación
        if self.current_phase == "post":
            # Se recuentan los pendientes: los ya publicados no vuelven a pasar.
            self._pub_validar_cotizaciones()
            self.write({"state": "posting", "post_ended_at": False,
                        "post_total": self.post_done + self._pub_pendientes_count()})
            self._log("Publicación reanudada. Quedan %d asientos en borrador."
                      % self._pub_pendientes_count())
            self._encolar_cron()
            return True
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
        for batch in self.search([("state", "=", "posting")], order="id"):
            batch._publicar_varias_tandas()
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
        self._apl_preparar_staging()
        # Línea base de las tablas por donde sale algo hacia el WMS: el
        # invariante 7 exige que no haya aparecido ni una fila nueva.
        base = self._inv_linea_base_wms()
        if base:
            self.env["ir.config_parameter"].sudo().set_param(
                "forum_partner_import.wms_base.%d" % self.id,
                ",".join("%s=%s" % (tabla, tope) for tabla, tope in sorted(base.items())))
        vals = {"state": "applying", "current_phase": "apply", "apply_ended_at": False,
                "apply_step": False}
        if not self.apply_started_at:
            # Primera vez: se numeran las celdas a aplicar, por ubicación. El
            # orden queda fijo en staging, así que reanudar retoma exactamente
            # donde quedó aunque se cambie el tamaño de tanda.
            t = self._staging_name()
            self.env.cr.execute("""
                UPDATE {t} s SET apply_seq = r.n, apply_resultado = NULL, apply_error = NULL,
                       apply_via = NULL
                  FROM (SELECT row_num,
                               ROW_NUMBER() OVER (ORDER BY col_excel, fila_excel) AS n
                          FROM {t} WHERE accion_efectiva = ANY(%s)) r
                 WHERE r.row_num = s.row_num
            """.format(t=t), (list(ACCIONES_QUANT),))
            total = self.env.cr.rowcount
            vals.update({
                "apply_total": total, "apply_offset": 0, "apply_processed": 0,
                "applied_count": 0, "apply_no_diff": 0, "apply_errors": 0, "apply_via_orm": 0,
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

    def _apl_preparar_staging(self):
        """Columnas e índices que la aplicación necesita en staging."""
        t = self._staging_name()
        cr = self.env.cr
        cr.execute("ALTER TABLE {t} ADD COLUMN IF NOT EXISTS apply_via varchar".format(t=t))
        cr.execute("CREATE INDEX IF NOT EXISTS {t}_apply_idx ON {t} (apply_seq)".format(t=t))

    # ==================================================================
    # Tandas
    # ==================================================================
    def _aplicar_varias_tandas(self):
        """Una tanda por corrida del cron, con reintentos ante choques."""
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
        # Idempotente: un batch arrancado con una versión anterior del módulo
        # llega a Reanudar sin las columnas que esta versión usa en staging.
        self._apl_preparar_staging()
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
        """Aplica las celdas `apply_seq` de la tanda y avanza el puntero."""
        self.ensure_one()
        t0 = time.time()
        desde = self.apply_offset + 1
        hasta = self.apply_offset + self.apply_batch_size
        self.env.cr.execute(
            "SELECT row_num FROM {t} WHERE apply_seq BETWEEN %s AND %s ORDER BY apply_seq"
            .format(t=self._staging_name()), (desde, hasta))
        filas = [r[0] for r in self.env.cr.fetchall()]
        cuenta = self._apl_procesar_filas(filas)
        self.write({
            "apply_offset": min(hasta, self.apply_total),
            "apply_processed": self.apply_processed + len(filas),
            "applied_count": self.applied_count + cuenta["aplicado"],
            "apply_no_diff": self.apply_no_diff + cuenta["sin_diferencia"],
            "apply_errors": self.apply_errors + cuenta["error"],
            "apply_via_orm": self.apply_via_orm + cuenta["orm"],
            "apply_layers_valued": self.apply_layers_valued + cuenta["capas_valor"],
            "apply_entries": self.apply_entries + cuenta["asientos"],
        })
        _logger.info(
            "[forum_partner_import][batch %s] aplicación %d-%d en %.1fs | ajustados=%d "
            "sin_diferencia=%d errores=%d | vía SQL=%d vía ORM=%d (%.1fs)",
            self.id, desde, min(hasta, self.apply_total), time.time() - t0,
            cuenta["aplicado"], cuenta["sin_diferencia"], cuenta["error"],
            len(filas) - cuenta["orm"], cuenta["orm"], cuenta["segundos_orm"])

    def _apl_procesar_filas(self, filas):
        """Aplica las celdas de staging `filas` (row_num), en el orden dado.

        Es el corazón de la tanda y lo que usa la prueba de paridad. No hace
        commit ni toca los contadores del batch.
        """
        self.ensure_one()
        cuenta = {"aplicado": 0, "sin_diferencia": 0, "error": 0, "orm": 0, "segundos_orm": 0.0,
                  "capas_valor": 0, "asientos": 0}
        if not filas:
            return cuenta
        # Lo llena `_apl_sql` con lo que generó la valuación de esta tanda. Va
        # como argumento y no como atributo de `self`: un recordset de Odoo
        # define __slots__ y no acepta atributos nuevos (AttributeError).
        contadores = {}
        cr = self.env.cr
        t = self._staging_name()
        # Nadie más crea ni mueve quants o capas mientras dura la tanda: el SQL
        # decide sobre el estado que lee (quant del par, candidatos FIFO).
        cr.execute("LOCK TABLE stock_quant IN SHARE ROW EXCLUSIVE MODE")
        cr.execute("LOCK TABLE stock_valuation_layer IN SHARE ROW EXCLUSIVE MODE")

        tiempos = self._apl_cronometro()
        productos_orm = self._apl_productos_orm(t, filas)
        cr.execute("SELECT row_num, product_id FROM {t} WHERE row_num = ANY(%s)".format(t=t), (filas,))
        producto_de = dict(cr.fetchall())
        filas_orm = [f for f in filas if producto_de[f] in productos_orm]
        filas_sql = [f for f in filas if producto_de[f] not in productos_orm]
        tiempos("clasificación (%d productos vía ORM)" % len(productos_orm))

        resultado, errores = {}, {}
        if filas_sql:
            self._apl_sql(t, filas_sql, resultado, tiempos, contadores)
        if filas_orm:
            t_orm = time.time()
            self._apl_orm(t, filas_orm, resultado, errores)
            cuenta["segundos_orm"] = time.time() - t_orm
            tiempos("camino ORM (%d celdas)" % len(filas_orm))

        filas_res = list(resultado)
        via = {f: ("orm" if producto_de[f] in productos_orm else "sql") for f in filas_res}
        cr.execute("""
            UPDATE {t} s SET apply_resultado = m.res, apply_error = m.err, apply_via = m.via
              FROM unnest(%s::bigint[], %s::varchar[], %s::text[], %s::varchar[])
                   AS m(row_num, res, err, via)
             WHERE s.row_num = m.row_num
        """.format(t=t), (filas_res, [resultado[f] for f in filas_res],
                          [errores.get(f) for f in filas_res], [via[f] for f in filas_res]))
        tiempos("registro en staging")
        valores = list(resultado.values())
        cuenta.update({
            "aplicado": valores.count("aplicado"),
            "sin_diferencia": valores.count("sin_diferencia"),
            "error": valores.count("error"),
            "orm": len(filas_orm),
            "capas_valor": contadores.get("capas_valor", 0),
            "asientos": contadores.get("asientos", 0),
        })
        _logger.info("[forum_partner_import][batch %s] tiempos de la tanda: %s", self.id, tiempos())
        return cuenta

    @staticmethod
    def _apl_cronometro():
        """Acumula (etapa, segundos) desde la marca anterior; sin argumentos devuelve el resumen."""
        marcas = {"t": time.time(), "etapas": []}

        def marcar(etapa=None):
            if etapa is None:
                return ", ".join("%s %.1fs" % e for e in marcas["etapas"])
            ahora = time.time()
            marcas["etapas"].append((etapa, ahora - marcas["t"]))
            marcas["t"] = ahora
        return marcar

    # ------------------------------------------------------------------
    # Clasificación
    # ------------------------------------------------------------------
    def _apl_productos_orm(self, t, filas):
        """Productos de la tanda que tienen que ir por el ORM.

        El SQL solo replica movimientos cuya valuación es cero de punta a punta.
        Todo lo demás —y lo que dispara efectos sobre otros documentos— va por
        `_apply_inventory`, con todas las celdas del producto en la tanda.
        """
        cr = self.env.cr
        # Una consulta por condición, cada una set-based sobre los productos y
        # ubicaciones de la tanda (con subconsultas correlacionadas por producto
        # la clasificación de 50.000 celdas tardaba más que la tanda entera).
        cr.execute("DROP TABLE IF EXISTS forum_apl_f")
        cr.execute("""
            CREATE TEMP TABLE forum_apl_f ON COMMIT DROP AS
            SELECT s.row_num, s.product_id, s.location_id, s.company_id, s.cantidad
              FROM {t} s WHERE s.row_num = ANY(%(filas)s)
        """.format(t=t), {"filas": filas})
        cr.execute("ANALYZE forum_apl_f")
        consultas = [
            # Costeo que el SQL no replica (solo FIFO) o seguimiento por lote.
            # OJO: tener costo ya NO manda al ORM. El SQL valúa las capas y crea
            # los asientos en borrador, que es el diseño del escenario de saldos
            # iniciales, donde todos los productos tienen costo: con el criterio
            # viejo caía el 100% de las celdas al ORM (medido) y la aplicación
            # pasaba de minutos a horas.
            """
            WITH p AS (SELECT DISTINCT product_id, company_id FROM forum_apl_f)
            SELECT p.product_id
              FROM p
              JOIN product_product pp ON pp.id = p.product_id
              JOIN product_template pt ON pt.id = pp.product_tmpl_id
              LEFT JOIN ir_property cm ON cm.name = 'property_cost_method' AND cm.company_id = p.company_id
                    AND cm.res_id = 'product.category,' || pt.categ_id
              LEFT JOIN ir_property cmd ON cmd.name = 'property_cost_method' AND cmd.company_id = p.company_id
                    AND cmd.res_id IS NULL
             WHERE coalesce(cm.value_text, cmd.value_text, 'standard') <> 'fifo'
                OR pt.tracking <> 'none'
            """,
            # Capas NEGATIVAS preexistentes: son las que el `_fifo_vacuum` va a
            # corregir con capas de ajuste, y esa corrección el SQL no la
            # replica. Las capas CON VALOR ya no mandan al ORM: son la norma en
            # saldos iniciales y el reparto FIFO las consume por SQL.
            """
            SELECT DISTINCT l.product_id
              FROM stock_valuation_layer l
              JOIN (SELECT DISTINCT product_id, company_id FROM forum_apl_f) p
                ON p.product_id = l.product_id AND p.company_id = l.company_id
             WHERE l.remaining_qty < 0
            """,
            # reservas en el quant de la celda (_free_reservation)
            """
            SELECT DISTINCT f.product_id
              FROM forum_apl_f f
              JOIN stock_quant q ON q.product_id = f.product_id AND q.location_id = f.location_id
             WHERE q.reserved_quantity <> 0
            """,
            # líneas pendientes del producto en la ubicación o sus hijas
            """
            WITH ubic AS (
                SELECT DISTINCT lf.id AS location_id, lm.id AS hija
                  FROM (SELECT DISTINCT location_id FROM forum_apl_f) u
                  JOIN stock_location lf ON lf.id = u.location_id
                  JOIN stock_location lm ON lm.parent_path LIKE lf.parent_path || '%%'
            )
            SELECT DISTINCT ml.product_id
              FROM stock_move_line ml
              JOIN ubic ON ubic.hija = ml.location_id
              JOIN forum_apl_f f ON f.product_id = ml.product_id AND f.location_id = ubic.location_id
             WHERE ml.state NOT IN ('done', 'cancel') AND ml.quantity <> 0
            """,
            # par sin quant con contado (lo crea el ORM)
            """
            SELECT DISTINCT f.product_id
              FROM forum_apl_f f
              LEFT JOIN stock_quant q ON q.product_id = f.product_id AND q.location_id = f.location_id
                    AND q.lot_id IS NULL AND q.package_id IS NULL AND q.owner_id IS NULL
             WHERE f.cantidad <> 0 AND q.id IS NULL
            """,
            # par con quants duplicados
            """
            SELECT DISTINCT f.product_id
              FROM forum_apl_f f
              JOIN stock_quant q ON q.product_id = f.product_id AND q.location_id = f.location_id
                    AND q.lot_id IS NULL AND q.package_id IS NULL AND q.owner_id IS NULL
             GROUP BY f.product_id, f.location_id HAVING count(*) > 1
            """,
        ]
        productos = set()
        for consulta in consultas:
            cr.execute(consulta)
            productos.update(r[0] for r in cr.fetchall())
        cr.execute("DROP TABLE forum_apl_f")
        return productos

    # ------------------------------------------------------------------
    # Camino SQL
    # ------------------------------------------------------------------
    def _apl_textos_orm(self, product_id, location_id):
        """Nombre del movimiento, tal cual lo arma el ORM en este entorno.

        Se le pide a `_get_inventory_move_values` sobre un quant en memoria, para
        que la traducción, el sufijo con el responsable y el de la fecha
        contable salgan de la misma función que usa `_apply_inventory`.
        """
        Quant = self.env["stock.quant"].with_user(self.inventory_user_id)
        if self.inventory_accounting_date:
            Quant = Quant.with_context(force_period_date=self.inventory_accounting_date)
        quant = Quant.new({"product_id": product_id, "location_id": location_id,
                           "user_id": self.inventory_user_id.id})
        ubicacion = self.env["stock.location"].browse(location_id)
        actualizado = quant._get_inventory_move_values(1.0, ubicacion, ubicacion)["name"]
        confirmado = quant._get_inventory_move_values(0.0, ubicacion, ubicacion)["name"]
        return actualizado, confirmado

    def _apl_defaults(self, modelo, explicitos):
        """(columnas, valores SQL) de los defaults del ORM que no se ponen a mano.

        Un create() del ORM guarda el default de cada campo que no viene en los
        valores (y NULL si no tiene). Se le piden al ORM con `default_get`, así
        entra lo que agregue cualquier módulo instalado. Los calculados y
        related stored no tienen default: esos van en `explicitos` y lo que
        falte se registra en el log.
        """
        Modelo = self.env[modelo].with_user(self.inventory_user_id)
        candidatos, sin_cubrir = [], []
        for nombre, campo in Modelo._fields.items():
            if nombre in explicitos or nombre == "id" or not campo.store or not campo.column_type:
                continue
            if campo.compute or campo.related:
                sin_cubrir.append(nombre)
                continue
            candidatos.append(nombre)
        defaults = Modelo.default_get(candidatos)
        columnas, valores, params = [], [], {}
        for nombre in candidatos:
            if nombre not in defaults:
                continue
            valor = Modelo._fields[nombre].convert_to_column(defaults[nombre], Modelo)
            if valor is None:
                continue
            clave = "d_%s_%s" % (modelo.replace(".", "_"), nombre)
            columnas.append('"%s"' % nombre)
            valores.append("%%(%s)s" % clave)
            params[clave] = valor
        if sin_cubrir:
            _logger.info("[forum_partner_import] %s: calculados sin valor explícito en la réplica: %s",
                         modelo, ", ".join(sin_cubrir))
        return columnas, valores, params

    def _apl_sql(self, t, filas, resultado, tiempos=None, contadores=None):
        """Réplica SQL de `_apply_inventory` para celdas con valuación cero."""
        tiempos = tiempos or self._apl_cronometro()
        cr = self.env.cr
        usuario = self.inventory_user_id
        Move = self.env["stock.move"]
        MoveLine = self.env["stock.move.line"]
        Layer = self.env["stock.valuation.layer"]
        Quant = self.env["stock.quant"]
        lang = self.env.lang or "en_US"
        ahora = fields.Datetime.now()
        hoy = fields.Date.today()

        # 1. Celdas de la tanda con su quant, la diferencia de este momento y
        #    todo lo que hace falta de producto, ubicación y compañía.
        cr.execute("DROP TABLE IF EXISTS forum_apl")
        cr.execute("""
            CREATE TEMP TABLE forum_apl ON COMMIT DROP AS
            SELECT s.row_num, s.apply_seq, s.product_id, s.location_id, s.company_id, s.cantidad,
                   q.id AS quant_id, coalesce(q.quantity, 0) AS qty, q.in_date AS q_in_date,
                   s.cantidad - coalesce(q.quantity, 0) AS diff,
                   abs(s.cantidad - coalesce(q.quantity, 0)) < u.rounding / 2 AS es_cero,
                   coalesce(q.quantity, 0) > u.rounding / 2 AS con_stock,
                   pt.uom_id, pt.categ_id, coalesce(pp.weight, 0) AS peso, pc.complete_name AS categ_name,
                   coalesce(pt.name ->> %(lang)s, pt.name ->> 'en_US') AS prod_name,
                   split_part(coalesce(pi.value_reference, pdef.value_reference), ',', 2)::int AS inv_loc,
                   cur.decimal_places AS dec_cia, {dec_rep} AS dec_rep,
                   NULL::int AS move_id, NULL::int AS ml_id, NULL::int AS svl_id,
                   0::numeric AS faltante,
                   -- Costo del producto en su compañía: el que usa una capa de
                   -- entrada (`_get_price_unit` cae en `standard_price` porque
                   -- un movimiento de inventario nace sin `price_unit`).
                   coalesce(sp.value_float, spd.value_float, 0) AS costo,
                   -- Cotización de la moneda de reporte a la fecha, para los
                   -- campos de tchistorico. Equivale a `_get_conversion_rate`.
                   {cotiz} AS cotiz,
                   -- Los rellena `_apl_fifo_valores` para las salidas.
                   0::numeric AS val_salida, 0::numeric AS costo_salida
              FROM {t} s
              JOIN stock_quant q ON q.product_id = s.product_id AND q.location_id = s.location_id
                               AND q.lot_id IS NULL AND q.package_id IS NULL AND q.owner_id IS NULL
              JOIN res_company c ON c.id = s.company_id
              JOIN res_currency cur ON cur.id = c.currency_id
              JOIN product_product pp ON pp.id = s.product_id
              JOIN product_template pt ON pt.id = pp.product_tmpl_id
              JOIN uom_uom u ON u.id = pt.uom_id
              JOIN product_category pc ON pc.id = pt.categ_id
              LEFT JOIN ir_property pi ON pi.name = 'property_stock_inventory'
                    AND pi.res_id = 'product.template,' || pt.id AND pi.company_id = s.company_id
              LEFT JOIN ir_property pdef ON pdef.name = 'property_stock_inventory'
                    AND pdef.res_id IS NULL AND pdef.company_id = s.company_id
              -- Costo del producto: la propiedad propia y, si no tiene, el
              -- default de la compañía. Es el mismo orden que resuelve el ORM.
              LEFT JOIN ir_property sp ON sp.name = 'standard_price'
                    AND sp.res_id = 'product.product,' || s.product_id
                    AND sp.company_id = s.company_id
              LEFT JOIN ir_property spd ON spd.name = 'standard_price'
                    AND spd.res_id IS NULL AND spd.company_id = s.company_id
             WHERE s.row_num = ANY(%(filas)s)
        """.format(t=t, dec_rep=(
            '(SELECT decimal_places FROM res_currency WHERE id = c."monedaDeReporte")'
            if "monedaDeReporte" in self.env["res.company"]._fields else "NULL::int"),
            cotiz=self._apl_sql_cotiz()),
            {"filas": filas, "lang": lang, "hoy": hoy})

        tiempos("SQL: tabla de trabajo")
        # Celdas sin quant (contado 0): no hay nada que aplicar.
        cr.execute("SELECT row_num FROM forum_apl")
        con_quant = {r[0] for r in cr.fetchall()}
        for fila in filas:
            if fila not in con_quant:
                resultado[fila] = "sin_diferencia"
        if not con_quant:
            return

        cr.execute("SELECT count(*) FROM forum_apl WHERE inv_loc IS NULL")
        if cr.fetchone()[0]:
            raise UserError(_("Hay productos sin ubicación de ajuste de inventario para su compañía."))

        # 2. Ids, pedidos a las secuencias en el orden del ORM: movimientos y
        #    líneas en el orden de las celdas; capas, primero las entradas.
        def pedir_ids(secuencia, orden, condicion="true"):
            cr.execute("SELECT row_num FROM forum_apl WHERE %s ORDER BY %s" % (condicion, orden))
            orden_filas = [r[0] for r in cr.fetchall()]
            cr.execute("SELECT nextval(%s) FROM generate_series(1, %s)", (secuencia, len(orden_filas)))
            ids = sorted(r[0] for r in cr.fetchall())
            return orden_filas, ids

        filas_ord, ids_move = pedir_ids("stock_move_id_seq", "apply_seq")
        _f, ids_ml = pedir_ids("stock_move_line_id_seq", "apply_seq")
        cr.execute("""
            UPDATE forum_apl a SET move_id = m.move_id, ml_id = m.ml_id
              FROM unnest(%s::bigint[], %s::int[], %s::int[]) AS m(row_num, move_id, ml_id)
             WHERE a.row_num = m.row_num
        """, (filas_ord, ids_move, ids_ml))
        filas_svl, ids_svl = pedir_ids("stock_valuation_layer_id_seq", "diff < 0, move_id", "NOT es_cero")
        if filas_svl:
            cr.execute("""
                UPDATE forum_apl a SET svl_id = m.svl_id
                  FROM unnest(%s::bigint[], %s::int[]) AS m(row_num, svl_id)
                 WHERE a.row_num = m.row_num
            """, (filas_svl, ids_svl))

        cr.execute("SELECT product_id, location_id FROM forum_apl LIMIT 1")
        producto_muestra, ubicacion_muestra = cr.fetchone()
        nombre_upd, nombre_conf = self._apl_textos_orm(producto_muestra, ubicacion_muestra)
        params = {
            "uid": usuario.id, "ahora": ahora, "hoy": hoy, "reason": self.inventory_reason,
            "nombre_upd": nombre_upd, "nombre_conf": nombre_conf,
        }

        tiempos("SQL: ids y textos")
        # 3. stock.move
        explicitos_move = {
            "id": "a.move_id", "company_id": "a.company_id", "product_id": "a.product_id",
            "product_uom": "a.uom_id",
            "location_id": "CASE WHEN a.diff > 0 AND NOT a.es_cero THEN a.inv_loc ELSE a.location_id END",
            "location_dest_id": "CASE WHEN a.diff > 0 AND NOT a.es_cero THEN a.location_id ELSE a.inv_loc END",
            "name": "CASE WHEN a.es_cero THEN %(nombre_conf)s ELSE %(nombre_upd)s END",
            "reference": "CASE WHEN a.es_cero THEN %(nombre_conf)s ELSE %(nombre_upd)s END",
            "origin": "%(reason)s", "state": "'done'",
            # calculado: prioridad del picking, '0' sin picking
            "priority": "'0'",
            "product_uom_qty": self._apl_num("stock.move", "product_uom_qty",
                                             "CASE WHEN a.es_cero THEN 0 ELSE abs(a.diff) END"),
            "product_qty": self._apl_num("stock.move", "product_qty",
                                         "CASE WHEN a.es_cero THEN 0 ELSE abs(a.diff) END"),
            "quantity": self._apl_num("stock.move", "quantity",
                                      "CASE WHEN a.es_cero THEN 0 ELSE abs(a.diff) END"),
            "picked": "true", "is_inventory": "true", "restrict_partner_id": "NULL",
            "scrapped": "coalesce(ld.scrap_location, false)",
            "date": "%(ahora)s",
            "create_uid": "%(uid)s", "write_uid": "%(uid)s",
            "create_date": "now() AT TIME ZONE 'UTC'", "write_date": "now() AT TIME ZONE 'UTC'",
        }
        if "weight" in Move._fields:
            params["dig_peso"] = self.env["decimal.precision"].precision_get("Stock Weight")
            explicitos_move["weight"] = self._apl_num(
                "stock.move", "weight",
                "CASE WHEN a.peso > 0 AND NOT a.es_cero THEN abs(a.diff) * a.peso ELSE 0 END")
        cols_d, vals_d, params_d = self._apl_defaults("stock.move", explicitos_move)
        params.update(params_d)
        cr.execute("""
            INSERT INTO stock_move ({cols})
            SELECT {vals}
              FROM forum_apl a
              JOIN stock_location ld ON ld.id = CASE WHEN a.diff > 0 AND NOT a.es_cero
                                                     THEN a.location_id ELSE a.inv_loc END
             ORDER BY a.apply_seq
        """.format(cols=", ".join(['"%s"' % c for c in explicitos_move] + cols_d),
                   vals=", ".join(list(explicitos_move.values()) + vals_d)), params)

        tiempos("SQL: stock_move")
        # 4. stock.move.line
        explicitos_ml = {
            "id": "a.ml_id", "move_id": "a.move_id", "company_id": "a.company_id",
            "product_id": "a.product_id", "product_uom_id": "a.uom_id",
            "location_id": "CASE WHEN a.diff > 0 AND NOT a.es_cero THEN a.inv_loc ELSE a.location_id END",
            "location_dest_id": "CASE WHEN a.diff > 0 AND NOT a.es_cero THEN a.location_id ELSE a.inv_loc END",
            "lot_id": "NULL", "package_id": "NULL", "result_package_id": "NULL", "owner_id": "NULL",
            "quantity": self._apl_num("stock.move.line", "quantity",
                                      "CASE WHEN a.es_cero THEN 0 ELSE abs(a.diff) END"),
            "quantity_product_uom": self._apl_num("stock.move.line", "quantity_product_uom",
                                                  "CASE WHEN a.es_cero THEN 0 ELSE abs(a.diff) END"),
            "picked": "true", "state": "'done'",
            "reference": "CASE WHEN a.es_cero THEN %(nombre_conf)s ELSE %(nombre_upd)s END",
            "product_category_name": "a.categ_name",
            "date": "%(ahora)s",
            "create_uid": "%(uid)s", "write_uid": "%(uid)s",
            "create_date": "now() AT TIME ZONE 'UTC'", "write_date": "now() AT TIME ZONE 'UTC'",
        }
        if "reason" in MoveLine._fields:
            explicitos_ml["reason"] = "%(reason)s"
        cols_d, vals_d, params_d = self._apl_defaults("stock.move.line", explicitos_ml)
        params.update(params_d)
        cr.execute("""
            INSERT INTO stock_move_line ({cols})
            SELECT {vals} FROM forum_apl a ORDER BY a.apply_seq
        """.format(cols=", ".join(['"%s"' % c for c in explicitos_ml] + cols_d),
                   vals=", ".join(list(explicitos_ml.values()) + vals_d)), params)

        tiempos("SQL: stock_move_line")
        # 5. Quant contado: cantidad, in_date y conteo limpio.
        ubicaciones = self.env["stock.location"].browse(
            sorted({r for r in self._apl_valores("location_id")}))
        proximas = {u.id: u._get_next_inventory_date() or None for u in ubicaciones}
        limpiar_extra = ""
        if "reason" in Quant._fields:
            limpiar_extra += ", reason = NULL"
        if "preset_reason_id" in Quant._fields:
            limpiar_extra += ", preset_reason_id = NULL"
        cr.execute("""
            UPDATE stock_quant q SET
                quantity = CASE WHEN a.es_cero THEN q.quantity ELSE {cantidad} END,
                in_date = CASE
                    WHEN a.es_cero THEN q.in_date
                    WHEN a.diff > 0 THEN CASE WHEN a.con_stock THEN least(q.in_date, %(ahora)s) ELSE %(ahora)s END
                    ELSE CASE WHEN a.con_stock THEN q.in_date ELSE %(ahora)s END
                END,
                -- Como el ORM: primero pone el contado y la diferencia, después los
                -- limpia a 0. Field.write no reescribe un valor igual, así que si
                -- ya era 0 queda lo que escribió "poner el contado".
                inventory_quantity = CASE WHEN s.cantidad = 0 THEN s.cantidad ELSE {cero_inv} END,
                inventory_diff_quantity = CASE WHEN s.cantidad - coalesce(q.quantity, 0) = 0
                                               THEN s.cantidad - coalesce(q.quantity, 0) ELSE {cero_dif} END,
                inventory_quantity_set = false,
                user_id = NULL, accounting_date = NULL, inventory_date = p.proxima,
                write_uid = %(uid)s, write_date = now() AT TIME ZONE 'UTC'
                {extra}
              FROM forum_apl a
              JOIN {t} s ON s.row_num = a.row_num
              LEFT JOIN unnest(%(ubic)s::int[], %(fechas)s::date[]) AS p(location_id, proxima)
                     ON p.location_id = a.location_id
             WHERE q.id = a.quant_id
        """.format(extra=limpiar_extra, t=t,
                   cantidad=self._apl_num("stock.quant", "quantity", "q.quantity + a.diff"),
                   cero_inv=self._apl_num("stock.quant", "inventory_quantity", "0"),
                   cero_dif=self._apl_num("stock.quant", "inventory_diff_quantity", "0")),
            dict(params, ubic=list(proximas), fechas=list(proximas.values())))

        tiempos("SQL: quants contados")
        # 6. Quant de la ubicación de ajuste: la suma de lo que movió cada
        #    producto; in_date de la última línea (orden de id, como el ORM).
        extra_quant = dict(self._inv_campos_extra_quant())
        extra_quant.pop("reason", None)
        cr.execute("""
            CREATE TEMP TABLE forum_apl_ajuste ON COMMIT DROP AS
            SELECT product_id, inv_loc,
                   sum(-diff) AS delta,
                   (array_agg(CASE WHEN diff > 0 THEN %(ahora)s
                                   WHEN con_stock THEN q_in_date ELSE %(ahora)s END
                              ORDER BY ml_id DESC))[1] AS in_date_final
              FROM forum_apl WHERE NOT es_cero
             GROUP BY product_id, inv_loc
        """, params)
        cr.execute("""
            UPDATE stock_quant q SET quantity = {cantidad}, in_date = g.in_date_final,
                   write_uid = %(uid)s, write_date = now() AT TIME ZONE 'UTC'
              FROM forum_apl_ajuste g
             WHERE q.product_id = g.product_id AND q.location_id = g.inv_loc
               AND q.lot_id IS NULL AND q.package_id IS NULL AND q.owner_id IS NULL
        """.format(cantidad=self._apl_num("stock.quant", "quantity", "q.quantity + g.delta")), params)
        # Quant nuevo en la ubicación de ajuste. Dos detalles del ORM:
        # - inventory_diff_quantity (inventory_quantity - quantity) se calcula al
        #   hacer flush, con la cantidad FINAL de la tanda, no con la primera línea;
        # - unit_value_report queda NULL: tchistorico lo asigna dentro del
        #   compute de value_report, y en un registro recién creado esa
        #   asignación no se guarda.
        extra_quant.pop("unit_value_report", None)
        cr.execute("""
            INSERT INTO stock_quant (
                product_id, location_id, company_id, storage_category_id, quantity,
                reserved_quantity, in_date, inventory_quantity_set, inventory_diff_quantity,
                create_uid, create_date, write_uid, write_date {cols_extra})
            SELECT g.product_id, g.inv_loc, l.company_id, l.storage_category_id, {cantidad},
                   {reservado}, g.in_date_final, false, {diferencia},
                   %(uid)s, now() AT TIME ZONE 'UTC', %(uid)s, now() AT TIME ZONE 'UTC' {vals_extra}
              FROM forum_apl_ajuste g
              JOIN stock_location l ON l.id = g.inv_loc
              JOIN res_company c ON c.id = l.company_id
             WHERE NOT EXISTS (SELECT 1 FROM stock_quant q
                                WHERE q.product_id = g.product_id AND q.location_id = g.inv_loc
                                  AND q.lot_id IS NULL AND q.package_id IS NULL AND q.owner_id IS NULL)
        """.format(cols_extra="".join(", %s" % c for c in extra_quant),
                   vals_extra="".join(", %s" % v for v in extra_quant.values()),
                   cantidad=self._apl_num("stock.quant", "quantity", "g.delta"),
                   reservado=self._apl_num("stock.quant", "reserved_quantity", "0"),
                   diferencia=self._apl_num("stock.quant", "inventory_diff_quantity", "-g.delta")),
            params)

        tiempos("SQL: quants de ajuste")
        # 7. Capas de valuación: entradas y salidas, todo en cero.
        #    Faltante de cada salida: lo que no cubren las capas con saldo
        #    (calculado antes de consumir, contando las entradas de la tanda).
        cr.execute("""
            WITH disp AS (
                SELECT l.product_id, l.company_id, sum(l.remaining_qty) AS disponible
                  FROM stock_valuation_layer l
                 WHERE l.remaining_qty > 0
                   AND (l.product_id, l.company_id) IN (SELECT product_id, company_id FROM forum_apl
                                                         WHERE diff < 0 AND NOT es_cero)
                 GROUP BY 1, 2
            ),
            entradas AS (
                SELECT product_id, company_id, sum(diff) AS cantidad
                  FROM forum_apl WHERE diff > 0 AND NOT es_cero GROUP BY 1, 2
            ),
            acum AS (
                SELECT row_num, product_id, company_id, -diff AS sale,
                       sum(-diff) OVER (PARTITION BY product_id, company_id ORDER BY move_id) AS acumulado
                  FROM forum_apl WHERE diff < 0 AND NOT es_cero
            )
            UPDATE forum_apl a
               SET faltante = greatest(0, least(x.sale, x.acumulado - coalesce(d.disponible, 0)
                                                        - coalesce(e.cantidad, 0)))
              FROM acum x
              LEFT JOIN disp d ON d.product_id = x.product_id AND d.company_id = x.company_id
              LEFT JOIN entradas e ON e.product_id = x.product_id AND e.company_id = x.company_id
             WHERE a.row_num = x.row_num
        """)
        capa = lambda campo, expr, moneda="dec_cia": self._apl_num(
            "stock.valuation.layer", campo, expr, moneda)
        # Valor de la capa. ENTRADA: cantidad × costo, redondeado a la moneda de
        # la compañía (`_prepare_in_svl_vals`). SALIDA: lo que el consumo FIFO
        # saca de las capas con saldo, más el faltante valuado al último costo
        # conocido si las capas no alcanzan (`_run_fifo`); se calcula en
        # `_apl_fifo_valores`, que deja `val_salida`, `costo_salida` y
        # `costo_salida` en la tabla de trabajo.
        val_entrada = "a.costo * a.diff"
        explicitos_svl = {
            "id": "a.svl_id", "company_id": "a.company_id", "product_id": "a.product_id",
            "categ_id": "a.categ_id", "stock_move_id": "a.move_id",
            "description": "%(nombre_upd)s || ' - ' || a.prod_name",
            "quantity": capa("quantity", "a.diff"),
            # unit_cost de una salida FIFO es tmp_value/cantidad, no el costo del
            # producto: lo pone _apl_fifo_valores. En una entrada es el costo.
            "unit_cost": capa("unit_cost", "CASE WHEN a.diff > 0 THEN a.costo "
                                           "ELSE a.costo_salida END"),
            "value": capa("value", "CASE WHEN a.diff > 0 THEN %s ELSE a.val_salida END"
                                   % val_entrada),
            "remaining_qty": capa("remaining_qty", "CASE WHEN a.diff > 0 THEN a.diff ELSE -a.faltante END"),
            # remaining_value de una entrada es su propio valor. En una SALIDA
            # queda NULL SIEMPRE, incluso con faltante: ni `_prepare_out_svl_vals`
            # ni `_run_fifo` escriben ese campo (la rama de stock negativo
            # devuelve remaining_qty, value y unit_cost, no remaining_value).
            # Verificado contra el ORM: con faltante de -819 el ORM dejó
            # remaining_value en 0/NULL, no el valor del faltante.
            "remaining_value": ("CASE WHEN a.diff > 0 THEN %s ELSE NULL END"
                                % capa("remaining_value", val_entrada)),
            "create_uid": "%(uid)s", "write_uid": "%(uid)s",
            "create_date": "now() AT TIME ZONE 'UTC'", "write_date": "now() AT TIME ZONE 'UTC'",
        }
        explicitos_svl.update(self._apl_tchistorico(Layer, capa, val_entrada))
        cols_d, vals_d, params_d = self._apl_defaults("stock.valuation.layer", explicitos_svl)
        params.update(params_d)
        insertar_capas = """
            INSERT INTO stock_valuation_layer ({cols})
            SELECT {vals}
              FROM forum_apl a JOIN res_company c ON c.id = a.company_id
             WHERE NOT a.es_cero AND {signo}
             ORDER BY a.svl_id
        """.format(cols=", ".join(['"%s"' % c for c in explicitos_svl] + cols_d),
                   vals=", ".join(list(explicitos_svl.values()) + vals_d),
                   signo="{signo}")
        # El INSERT va en DOS pasos, y el orden no es un detalle: el ORM valúa
        # primero todas las entradas del lote y después las salidas, así que las
        # capas de entrada RECIÉN CREADAS son candidatas del consumo FIFO de las
        # salidas de la misma tanda. Insertarlas todas juntas dejaría a las
        # salidas sin ver esas candidatas y el valor saldría distinto.
        cr.execute(insertar_capas.format(signo="a.diff > 0"), params)
        tiempos("SQL: capas de entrada")

        # Con las entradas ya en la tabla, se resuelve el consumo FIFO: cuánto
        # saca cada salida de cada capa con saldo y a qué costo.
        self._apl_fifo_valores(params)
        tiempos("SQL: reparto FIFO")

        cr.execute(insertar_capas.format(signo="a.diff < 0"), params)

        tiempos("SQL: capas de salida")
        #    Consumo FIFO: se descuenta de cada capa candidata lo que las
        #    salidas le tomaron (`forum_apl_toma`, que armó `_apl_fifo_valores`).
        #    Se baja también `remaining_value`: con capas en cero no hacía falta,
        #    pero acá las entradas del ajuste tienen valor y el ORM descuenta los
        #    dos campos (`candidate_vals` de `_run_fifo`).
        cr.execute("""
            WITH consumido AS (
                SELECT capa_id, sum(toma) AS qty, sum(valor_tomado) AS valor
                  FROM forum_apl_toma GROUP BY 1
            )
            UPDATE stock_valuation_layer l
               SET remaining_qty = {consumo_qty},
                   remaining_value = {consumo_val},
                   write_uid = %(uid)s, write_date = now() AT TIME ZONE 'UTC'
              FROM consumido k, res_company c, res_currency cur
             WHERE l.id = k.capa_id AND c.id = l.company_id AND cur.id = c.currency_id
        """.format(
            # `remaining_qty` es un Float con digits fijos y `remaining_value` un
            # Monetary: la escala de este último sale de la moneda de la compañía
            # de la capa, que acá viene del JOIN y no de la tabla de trabajo.
            consumo_qty=self._apl_num("stock.valuation.layer", "remaining_qty",
                                      "l.remaining_qty - k.qty", None),
            consumo_val=("round((coalesce(l.remaining_value, 0) - k.valor)::numeric, "
                         "cur.decimal_places)"),
        ), params)

        tiempos("SQL: consumo FIFO")
        # 7 bis. Asientos contables EN BORRADOR, uno por capa con valor.
        #        Los contadores NO van en `resultado`: ese dict es {fila: estado}
        #        y se escribe tal cual en staging. Van en `contadores`, que pasa
        #        `_apl_procesar_filas` y lee al cerrar la tanda.
        asientos = self._apl_asientos(params)
        # Va acá y no dentro de `_apl_asientos` porque tiene que correr SIEMPRE:
        # el valor de reporte del quant depende de las capas del producto, y esas
        # cambian aunque la tanda no genere ni un asiento (capas con valor cero).
        self._apl_recalcular_localizacion()
        # Capas con valor de ESTA tanda y de ESTE camino: se cuentan por los
        # svl_id que repartió la tanda, no por fecha de creación (el camino ORM
        # crea las suyas en el mismo instante y quedarían sumadas dos veces).
        cr.execute("""
            SELECT count(*) FROM stock_valuation_layer l
             WHERE l.id = ANY(%s) AND round(l.value::numeric, 2) <> 0
        """, ([svl for svl in self._apl_valores("svl_id") if svl],))
        if contadores is not None:
            contadores.update({"asientos": asientos, "capas_valor": cr.fetchone()[0]})
        tiempos("SQL: asientos en borrador")
        # 8. Última fecha de inventario de las ubicaciones.
        cr.execute("""
            UPDATE stock_location SET last_inventory_date = %(hoy)s,
                   write_uid = %(uid)s, write_date = now() AT TIME ZONE 'UTC'
             WHERE id IN (SELECT DISTINCT location_id FROM forum_apl)
               AND last_inventory_date IS DISTINCT FROM %(hoy)s
        """, params)

        tiempos("SQL: ubicaciones")
        cr.execute("SELECT row_num, es_cero FROM forum_apl")
        for fila, es_cero in cr.fetchall():
            resultado[fila] = "sin_diferencia" if es_cero else "aplicado"
        cr.execute("DROP TABLE forum_apl_ajuste")
        cr.execute("DROP TABLE forum_apl")
        # Todo lo anterior tocó tablas por SQL: que el ORM no siga con caché vieja.
        for modelo in ("stock.quant", "stock.move", "stock.move.line",
                       "stock.valuation.layer", "stock.location"):
            self.env[modelo].invalidate_model()

    # ==================================================================
    # Verificación exhaustiva por invariantes
    # ==================================================================
    def action_verificar_invariantes(self):
        """Corre el set de invariantes a pedido y deja el informe en el batch."""
        self.ensure_one()
        if not self._es_inventario():
            raise UserError(_("Solo un ajuste de inventario se verifica."))
        self._verificar_invariantes()
        return self._notificar(
            _("Verificación terminada"),
            _("Resultado: %s. El detalle queda en el informe del batch.")
            % dict(self._fields["check_state"].selection)[self.check_state])

    def _inv_linea_base_wms(self):
        """{tabla: max(id)} de las tablas por donde SALE algo hacia el WMS.

        Se guarda al arrancar la aplicación para que el invariante pueda exigir
        que no haya aparecido ni una fila nueva. No alcanza con mirar la
        configuración: `wis.sync.queue._encolar` escribe sin consultar si la
        comunicación está habilitada, así que la cola puede llenarse igual.
        """
        cr = self.env.cr
        base = {}
        for tabla in TABLAS_WMS_SALIENTES:
            cr.execute("SELECT to_regclass(%s)", (tabla,))
            if not cr.fetchone()[0]:
                continue
            cr.execute("SELECT coalesce(max(id), 0) FROM %s" % tabla)
            base[tabla] = cr.fetchone()[0]
        return base

    def _verificar_invariantes(self):
        """Set de invariantes sobre el 100% de lo generado por este ajuste.

        No es un muestreo: cada consulta recorre todas las filas del ajuste y
        devuelve la cantidad de violaciones y un ejemplo. Si alguna falla, el
        batch queda con `check_state = 'fallo'` y el detalle en `check_report`.

        Corre dos veces: al terminar la aplicación (los invariantes 1 a 4, 6 y 7)
        y otra vez al terminar la publicación (ahí suman el 5 y el 8).
        """
        self.ensure_one()
        cr = self.env.cr
        t = self._staging_name()
        publicado = self.state == "posted" or self.post_done
        lineas, violaciones = [], 0

        def revisar(titulo, sql, params=None, ejemplo_sql=None):
            nonlocal violaciones
            cr.execute(sql, params or {})
            n = cr.fetchone()[0] or 0
            violaciones += n
            detalle = ""
            if n and ejemplo_sql:
                cr.execute(ejemplo_sql, params or {})
                filas = cr.fetchall()[:3]
                detalle = " | ejemplos: %s" % ", ".join(str(f) for f in filas)
            lineas.append("%s %s: %d violaciones%s"
                          % ("OK  " if not n else "FALLA", titulo, n, detalle))

        # 1. La cantidad del quant es igual al contado, en todas las celdas.
        revisar("1. quant.quantity = contado del archivo", """
            SELECT count(*) FROM {t} s
              JOIN stock_quant q ON q.id = s.quant_id
             WHERE s.apply_resultado IN ('aplicado', 'sin_diferencia')
               AND round(q.quantity::numeric, 4) <> round(s.cantidad::numeric, 4)
        """.format(t=t), ejemplo_sql="""
            SELECT s.row_num, s.product_id, s.location_id, q.quantity, s.cantidad
              FROM {t} s JOIN stock_quant q ON q.id = s.quant_id
             WHERE s.apply_resultado IN ('aplicado', 'sin_diferencia')
               AND round(q.quantity::numeric, 4) <> round(s.cantidad::numeric, 4) LIMIT 3
        """.format(t=t))

        # 2. Cada celda aplicada tiene exactamente un movimiento done con su línea.
        revisar("2. una celda aplicada = un movimiento done con su línea", """
            SELECT count(*) FROM (
                SELECT s.row_num,
                       (SELECT count(*) FROM stock_move m
                         WHERE m.is_inventory AND m.state = 'done'
                           AND m.product_id = s.product_id
                           AND (m.location_id = s.location_id OR m.location_dest_id = s.location_id)
                           AND m.create_date >= %(desde)s) AS moves
                  FROM {t} s WHERE s.apply_resultado = 'aplicado') x
             WHERE moves = 0
        """.format(t=t), {"desde": self.apply_started_at})

        # 3. Capas: valor de una entrada = cantidad × costo, y remaining coherente.
        # 3a. Consistencia interna de la capa: su valor es su cantidad por su
        #     costo unitario. NO se compara contra el `standard_price` del
        #     producto, porque `_run_fifo` lo REESCRIBE durante la corrida
        #     (`product.standard_price = value_svl / quantity_svl`) en los
        #     productos que pasan por el camino ORM: la capa quedó bien con el
        #     costo de su momento y el de la propiedad ya es otro. Comparar
        #     contra la propiedad daba 374 falsos positivos en 17 productos que
        #     habían pasado por los dos caminos.
        revisar("3a. capa: value = cantidad × unit_cost", """
            SELECT count(*) FROM stock_valuation_layer l
              JOIN stock_move m ON m.id = l.stock_move_id
              JOIN res_company c ON c.id = l.company_id
              JOIN res_currency cur ON cur.id = c.currency_id
             WHERE m.is_inventory AND l.create_date >= %(desde)s AND l.quantity > 0
               AND round(l.value::numeric, cur.decimal_places)
                   <> round((l.quantity * l.unit_cost)::numeric, cur.decimal_places)
        """, {"desde": self.apply_started_at})
        # 3a bis. Y para las capas que hizo el SQL —donde el costo no se
        #     reescribe— sí se exige que el unit_cost sea el del producto.
        revisar("3a bis. capa por SQL: unit_cost = standard_price del producto", """
            SELECT count(*) FROM stock_valuation_layer l
              JOIN stock_move m ON m.id = l.stock_move_id
              JOIN ir_property ip ON ip.name = 'standard_price'
                   AND ip.company_id = l.company_id
                   AND ip.res_id = 'product.product,' || l.product_id
             WHERE m.is_inventory AND l.create_date >= %(desde)s AND l.quantity > 0
               AND l.product_id NOT IN (SELECT DISTINCT product_id FROM {t}
                                         WHERE apply_via = 'orm' AND product_id IS NOT NULL)
               AND round(l.unit_cost::numeric, 2) <> round(ip.value_float::numeric, 2)
        """.format(t=t), {"desde": self.apply_started_at})
        revisar("3b. ninguna capa con remaining_qty > cantidad", """
            SELECT count(*) FROM stock_valuation_layer l
              JOIN stock_move m ON m.id = l.stock_move_id
             WHERE m.is_inventory AND l.create_date >= %(desde)s
               AND l.quantity > 0 AND l.remaining_qty > l.quantity
        """, {"desde": self.apply_started_at})
        revisar("3c. remaining_value NULL o 0 en las salidas", """
            SELECT count(*) FROM stock_valuation_layer l
              JOIN stock_move m ON m.id = l.stock_move_id
             WHERE m.is_inventory AND l.create_date >= %(desde)s
               AND l.quantity < 0 AND coalesce(l.remaining_value, 0) <> 0
        """, {"desde": self.apply_started_at})

        # 4. Cada capa con valor tiene asiento, balanceado y por su importe.
        revisar("4a. capa con valor sin asiento", """
            SELECT count(*) FROM stock_valuation_layer l
              JOIN stock_move m ON m.id = l.stock_move_id
              JOIN res_company c ON c.id = l.company_id
              JOIN res_currency cur ON cur.id = c.currency_id
             WHERE m.is_inventory AND l.create_date >= %(desde)s
               AND round(l.value::numeric, cur.decimal_places) <> 0
               AND l.account_move_id IS NULL
        """, {"desde": self.apply_started_at})
        revisar("4b. asiento desbalanceado", """
            SELECT count(*) FROM (
                SELECT l.move_id
                  FROM account_move_line l
                  JOIN account_move am ON am.id = l.move_id
                  JOIN stock_move m ON m.id = am.stock_move_id
                  JOIN res_company c ON c.id = am.company_id
                  JOIN res_currency cur ON cur.id = c.currency_id
                 WHERE m.is_inventory AND am.create_date >= %(desde)s
                 GROUP BY l.move_id, cur.decimal_places
                HAVING round(sum(l.balance)::numeric, cur.decimal_places) <> 0) x
        """, {"desde": self.apply_started_at})
        revisar("4c. importe del asiento distinto del valor de su capa", """
            SELECT count(*) FROM stock_valuation_layer l
              JOIN account_move am ON am.id = l.account_move_id
              JOIN stock_move m ON m.id = am.stock_move_id
              JOIN res_company c ON c.id = am.company_id
              JOIN res_currency cur ON cur.id = c.currency_id
             WHERE m.is_inventory AND am.create_date >= %(desde)s
               AND round(abs(l.value)::numeric, cur.decimal_places) <> (
                   SELECT round(sum(x.debit)::numeric, cur.decimal_places)
                     FROM account_move_line x WHERE x.move_id = am.id)
        """, {"desde": self.apply_started_at})
        # Las tres cuentas que el ORM puede haber usado, resueltas con su misma
        # precedencia (ver `_apl_sql_prop_categ`): valuación, `acc_src` y
        # `acc_dest`. Con `IS DISTINCT FROM` y no `NOT IN`: un `NOT IN` con un
        # NULL adentro da NULL, y el control viejo no verificaba nada justo en
        # las categorías que se apoyan en el default de la compañía.
        #
        # Se resuelven una vez por (compañía, categoría) y no por línea. 🔴 El
        # `MATERIALIZED` no es decorativo: sin él Postgres
        # inlinea el CTE y ejecuta las subconsultas como SubPlan dentro del
        # Join Filter, una vez por cada una de las 1,6 M de líneas. Medido sobre
        # el batch 11: 21,9 s sin materializar contra 1,6 s con.
        revisar("4d. cuentas distintas de las de la categoría del producto", """
            WITH cat AS MATERIALIZED (
                SELECT c.id AS company_id, pc.id AS categ_id,
                       {val} AS cta_valuacion, {ent} AS cta_entrada, {sal} AS cta_salida
                  FROM res_company c CROSS JOIN product_category pc
            )
            SELECT count(*) FROM account_move_line l
              JOIN account_move am ON am.id = l.move_id
              JOIN stock_move m ON m.id = am.stock_move_id
              JOIN product_product pp ON pp.id = l.product_id
              JOIN product_template pt ON pt.id = pp.product_tmpl_id
              JOIN stock_location lsrc ON lsrc.id = m.location_id
              JOIN stock_location ldst ON ldst.id = m.location_dest_id
              JOIN cat k ON k.company_id = am.company_id AND k.categ_id = pt.categ_id
             WHERE m.is_inventory AND am.create_date >= %(desde)s
               AND l.account_id IS DISTINCT FROM k.cta_valuacion
               AND l.account_id IS DISTINCT FROM coalesce(lsrc.valuation_out_account_id,
                                                          k.cta_entrada)
               AND l.account_id IS DISTINCT FROM (
                   CASE WHEN ldst.usage IN ('production', 'inventory')
                        THEN coalesce(ldst.valuation_in_account_id, k.cta_salida)
                        ELSE k.cta_salida END)
        """.format(val=self._apl_sql_prop_categ(
                       "property_stock_valuation_account_id", "pc.id", "c.id"),
                   ent=self._apl_sql_prop_categ(
                       "property_stock_account_input_categ_id", "pc.id", "c.id"),
                   sal=self._apl_sql_prop_categ(
                       "property_stock_account_output_categ_id", "pc.id", "c.id")),
           {"desde": self.apply_started_at})

        # 4e/4f: los dos controles que faltaban sobre el asiento EN BORRADOR.
        # Hasta ahora todo lo de la familia 4 miraba las líneas, y la cabecera
        # quedaba sin verificar: un asiento con las líneas perfectas y los
        # importes de cabecera en NULL pasaba los cuatro controles y se veía
        # como `0,00 $` en la pantalla de revisión.
        revisar("4e. cabecera del asiento sin el importe de sus líneas", """
            SELECT count(*) FROM account_move am
              JOIN stock_move m ON m.id = am.stock_move_id
              JOIN res_company c ON c.id = am.company_id
              JOIN res_currency cur ON cur.id = c.currency_id
              JOIN LATERAL (SELECT sum(l.debit) AS debe FROM account_move_line l
                             WHERE l.move_id = am.id) x ON true
             WHERE m.is_inventory AND am.create_date >= %(desde)s
               AND round(x.debe::numeric, cur.decimal_places) <> 0
               AND coalesce(am.amount_total, 0)
                   <> round(x.debe::numeric, cur.decimal_places)
        """, {"desde": self.apply_started_at})
        # El diseño dice «un asiento por capa con valor distinto de cero». Si
        # alguna vez se crea uno con todas sus líneas en cero, es que la
        # condición de creación se rompió: sin este control se vería igual que
        # el defecto de la cabecera, y son cosas distintas.
        revisar("4f. asiento del ajuste con todas sus líneas en cero", """
            SELECT count(*) FROM account_move am
              JOIN stock_move m ON m.id = am.stock_move_id
             WHERE m.is_inventory AND am.create_date >= %(desde)s
               AND NOT EXISTS (SELECT 1 FROM account_move_line l
                                WHERE l.move_id = am.id AND l.debit <> 0)
        """, {"desde": self.apply_started_at})

        # 6. Sin quants duplicados, sin conteos pendientes, sin asientos huérfanos.
        revisar("6a. par producto/ubicación con más de un quant", """
            SELECT count(*) FROM (
                SELECT q.product_id, q.location_id FROM stock_quant q
                  JOIN (SELECT DISTINCT product_id, location_id FROM {t}
                         WHERE apply_seq IS NOT NULL) s
                    ON s.product_id = q.product_id AND s.location_id = q.location_id
                 WHERE q.lot_id IS NULL AND q.package_id IS NULL AND q.owner_id IS NULL
                 GROUP BY 1, 2 HAVING count(*) > 1) x
        """.format(t=t))
        revisar("6b. conteo pendiente sin aplicar", """
            SELECT count(*) FROM {t} s
              JOIN stock_quant q ON q.id = s.quant_id
             WHERE s.apply_resultado IN ('aplicado', 'sin_diferencia')
               AND q.inventory_quantity_set
        """.format(t=t))

        # 7. El WMS: no salió nada hacia afuera durante la corrida.
        base = self.env["ir.config_parameter"].sudo().get_param(
            "forum_partner_import.wms_base.%d" % self.id)
        if base:
            for parte in base.split(","):
                tabla, _sep, tope = parte.partition("=")
                if not _sep:
                    continue
                revisar("7. sin envíos nuevos al WMS en %s" % tabla,
                        "SELECT count(*) FROM %s WHERE id > %%(tope)s" % tabla,
                        {"tope": int(tope)})
        else:
            lineas.append("--   7. WMS: sin línea base registrada (batch anterior a esta versión)")

        # 5 y 8: solo tienen sentido con los asientos ya publicados.
        if publicado:
            revisar("5a. asientos del ajuste que quedaron en borrador", """
                SELECT count(*) FROM account_move am
                  JOIN stock_move m ON m.id = am.stock_move_id
                 WHERE m.is_inventory AND am.create_date >= %(desde)s AND am.state = 'draft'
            """, {"desde": self.apply_started_at})
            # Duplicados y huecos se miran sobre TODO el diario en el rango del
            # ajuste, no solo sobre los asientos del ajuste: el diario puede
            # tener asientos ajenos intercalados (en la copia había 41 previos
            # con el mismo prefijo), y compararlos solo entre ellos daba huecos
            # que no existen.
            revisar("5b. numeración del diario duplicada en el rango del ajuste", """
                SELECT count(*) FROM (
                    SELECT sequence_prefix, sequence_number
                      FROM account_move
                     WHERE state = 'posted' AND sequence_prefix IN (
                           SELECT DISTINCT am.sequence_prefix FROM account_move am
                             JOIN stock_move m ON m.id = am.stock_move_id
                            WHERE m.is_inventory AND am.create_date >= %(desde)s)
                     GROUP BY 1, 2 HAVING count(*) > 1) x
            """, {"desde": self.apply_started_at})
            # 5c. Huecos en la numeración. Sin ventana y a propósito: la versión
            # con `lag()` recorría `account_move` entera y calculaba el rango con
            # subconsultas CORRELACIONADAS por prefijo (se reevalúan por fila),
            # lo que medido sobre 829k asientos pasaba de 1 h 40 min volcando
            # 161 MB a disco. Si en el rango no falta ningún número, entonces
            # `count(distinct) = max - min + 1`: son dos agregados sobre
            # `account_move_sequence_index`, que ya existe en el core
            # (journal_id, sequence_prefix DESC, sequence_number DESC, name).
            # El rango del ajuste se resuelve UNA vez en el CTE.
            # Sigue mirando TODO el diario dentro del rango (no solo los asientos
            # del ajuste): los asientos ajenos intercalados no son huecos.
            # Nota: el viejo contaba saltos y este cuenta prefijos con huecos; el
            # valor esperado es 0 en los dos.
            rango_5c = """
                WITH rango AS (
                    SELECT am.sequence_prefix AS pref,
                           min(am.sequence_number) AS desde_n,
                           max(am.sequence_number) AS hasta_n
                      FROM account_move am
                      JOIN stock_move m ON m.id = am.stock_move_id
                     WHERE m.is_inventory AND am.create_date >= %(desde)s
                       AND am.state = 'posted' AND am.sequence_prefix IS NOT NULL
                     GROUP BY am.sequence_prefix)
                SELECT r.pref, r.desde_n, r.hasta_n,
                       count(DISTINCT a.sequence_number) AS presentes,
                       (r.hasta_n - r.desde_n + 1) AS esperados
                  FROM rango r
                  JOIN account_move a
                    ON a.sequence_prefix = r.pref
                   AND a.sequence_number BETWEEN r.desde_n AND r.hasta_n
                   AND a.state = 'posted'
                 GROUP BY r.pref, r.desde_n, r.hasta_n
                HAVING count(DISTINCT a.sequence_number) <> (r.hasta_n - r.desde_n + 1)
            """
            revisar("5c. huecos en la numeración del diario en el rango del ajuste",
                    "SELECT count(*) FROM (%s) x" % rango_5c,
                    {"desde": self.apply_started_at},
                    ejemplo_sql="%s LIMIT 3" % rango_5c)
            revisar("8. suma del diario distinta de la suma de las capas", """
                SELECT count(*) FROM (
                    SELECT round(sum(l.debit)::numeric, 2) AS diario,
                           (SELECT round(sum(abs(sl.value))::numeric, 2)
                              FROM stock_valuation_layer sl
                              JOIN stock_move sm ON sm.id = sl.stock_move_id
                             WHERE sm.is_inventory AND sl.create_date >= %(desde)s
                               AND sl.account_move_id IS NOT NULL) AS capas
                      FROM account_move_line l
                      JOIN account_move am ON am.id = l.move_id
                      JOIN stock_move m ON m.id = am.stock_move_id
                     WHERE m.is_inventory AND am.create_date >= %(desde)s
                ) x WHERE diario IS DISTINCT FROM capas
            """, {"desde": self.apply_started_at})

        informe = "\n".join(lineas)
        self.write({
            "check_state": "ok" if not violaciones else "fallo",
            "check_report": informe,
            "check_at": fields.Datetime.now(),
        })
        self._log("Verificación por invariantes: %s (%d violaciones).\n%s"
                  % ("todo verde" if not violaciones else "CON VIOLACIONES",
                     violaciones, informe))
        return violaciones

    # ==================================================================
    # Fase 3: publicación de los asientos (por ORM, deliberadamente)
    # ==================================================================
    def action_publicar_asientos(self):
        """Valida y deja la publicación de los asientos en manos del cron.

        Publicar va por el ORM y no por SQL a propósito: la numeración del
        diario es correlativa legal y el balanceo y los hooks los tiene que
        firmar Odoo. Lo único que hace esta fase es `action_post` por tandas.
        """
        self.ensure_one()
        if not self._es_inventario():
            raise UserError(_("Solo un ajuste de inventario publica asientos."))
        if self.state != "applied":
            raise UserError(_("Primero tiene que terminar la aplicación del ajuste."))
        if self.post_batch_size < 1:
            raise UserError(_("El tamaño de tanda de publicación debe ser mayor a cero."))

        self._pub_validar_cotizaciones()
        self._apl_cancelacion_pedida()
        # Rango de ids de los asientos a publicar, para que las tandas no tengan
        # que traversar `stock_move_id.is_inventory` (7,1 ms contra 0,7 ms por
        # tanda, medido sobre 817.007 borradores). Se guarda una sola vez.
        self.env.cr.execute("""
            SELECT min(am.id), max(am.id), count(*)
              FROM account_move am
              JOIN stock_move m ON m.id = am.stock_move_id
             WHERE m.is_inventory AND am.state = 'draft'
        """)
        desde, hasta, total = self.env.cr.fetchone()
        if not total:
            raise UserError(_("No hay asientos en borrador de este ajuste para publicar."))
        self.env["ir.config_parameter"].sudo().set_param(
            self.PARAM_RANGO_ASIENTOS % self.id, "%d-%d" % (desde, hasta))
        vals = {"state": "posting", "current_phase": "post", "post_ended_at": False,
                "post_step": False}
        if not self.post_started_at:
            vals.update({"post_total": total, "post_done": 0, "post_errors": 0,
                         "post_started_at": fields.Datetime.now()})
        else:
            # Retomando: el total es lo ya publicado MÁS lo que queda. Con solo
            # los pendientes, `post_done` (que conserva lo de la corrida
            # anterior) pasaba el total y la pantalla mostraba 101,3 %.
            vals["post_total"] = self.post_done + total
        self.write(vals)
        self._log("Publicación iniciada. %d asientos en borrador, tandas de %d."
                  % (total, self.post_batch_size))
        self.env.cr.commit()
        self._encolar_cron()
        return True

    PARAM_RANGO_ASIENTOS = "forum_partner_import.rango_asientos.%d"

    def _pub_dominio_borrador(self, rango=True):
        """Asientos en borrador generados por la aplicación de ESTE batch.

        Se identifican por el movimiento de inventario que los originó: el SQL
        les puso `stock_move_id`, igual que el ORM.

        Con `rango`, y si la publicación ya guardó el rango de ids, se usa ese
        rango en lugar de traversar `stock_move_id.is_inventory`. La diferencia
        no es cosmética: **medido sobre 817.007 borradores, la búsqueda de una
        tanda pasa de 7,1 ms a 0,7 ms**, porque el traversal resuelve una
        subconsulta sobre los 847.000 movimientos de inventario en cada tanda.
        """
        self.ensure_one()
        if rango:
            guardado = self.env["ir.config_parameter"].sudo().get_param(
                self.PARAM_RANGO_ASIENTOS % self.id)
            if guardado:
                desde, _sep, hasta = guardado.partition("-")
                return [
                    ("state", "=", "draft"),
                    ("stock_move_id", "!=", False),
                    ("id", ">=", int(desde)),
                    ("id", "<=", int(hasta)),
                ]
        return [
            ("state", "=", "draft"),
            ("stock_move_id", "!=", False),
            ("stock_move_id.is_inventory", "=", True),
        ]

    def _pub_pendientes_count(self):
        self.ensure_one()
        return self.env["account.move"].sudo().search_count(self._pub_dominio_borrador())

    def _pub_validar_cotizaciones(self):
        """Frena ANTES de arrancar si falta la cotización de alguna fecha.

        La copia de `aml_secondary_currency` que gana por `addons_path` es la de
        `general_primate`, que busca la cotización con la **fecha exacta** del
        asiento y levanta `UserError` desde el `_post()`. Sin este control, la
        publicación reventaría a mitad de una tanda y habría que reanudar a
        ciegas. Ver FINDINGS.md.
        """
        self.ensure_one()
        Company = self.env["res.company"]
        if "secondary_currency_id" not in Company._fields:
            return
        cr = self.env.cr
        cr.execute("""
            SELECT DISTINCT m.company_id, m.date, c.secondary_currency_id
              FROM account_move m
              JOIN stock_move sm ON sm.id = m.stock_move_id
              JOIN res_company c ON c.id = m.company_id
             WHERE m.state = 'draft' AND sm.is_inventory
               AND c.secondary_currency_id IS NOT NULL
        """)
        faltan = []
        for company_id, fecha, moneda_id in cr.fetchall():
            cr.execute("""
                SELECT 1 FROM res_currency_rate
                 WHERE currency_id = %s AND name = %s
                   AND (company_id = %s OR company_id IS NULL) LIMIT 1
            """, (moneda_id, fecha, company_id))
            if not cr.fetchone():
                faltan.append((fecha, Company.browse(company_id).display_name,
                               self.env["res.currency"].browse(moneda_id).name))
        if faltan:
            detalle = "\n".join("- %s, %s, moneda %s" % f for f in faltan)
            raise UserError(_(
                "Falta la cotización de la moneda secundaria para la fecha exacta "
                "de los asientos. La publicación fallaría a mitad de tanda.\n\n%s\n\n"
                "Cargá la cotización de esas fechas (en producción la carga el cron "
                "del BCU) y volvé a iniciar la publicación.") % detalle)

    def _publicar_varias_tandas(self):
        """Una tanda de publicación por corrida del cron, con reintentos."""
        self.ensure_one()
        self.invalidate_recordset(["state", "post_done", "post_total"])
        if self.state != "posting":
            return
        if self._apl_cancelacion_pedida():
            self.write({"state": "cancel", "post_ended_at": fields.Datetime.now()})
            self._log("Publicación cancelada por el usuario con %d de %d asientos publicados."
                      % (self.post_done, self.post_total))
            self.env.cr.commit()
            return
        for intento in range(1, REINTENTOS_TANDA + 1):
            try:
                quedan = self._publicar_tanda()
                self.env.cr.commit()
                break
            except Exception as e:
                self.env.cr.rollback()
                self.env.clear()
                if isinstance(e, TransactionRollbackError) and intento < REINTENTOS_TANDA:
                    _logger.warning(
                        "[forum_partner_import][batch %s] la tanda de publicación chocó con "
                        "otra transacción (%s); reintento %d de %d",
                        self.id, e, intento + 1, REINTENTOS_TANDA)
                    continue
                self.write({"state": "error", "post_ended_at": fields.Datetime.now()})
                self._log("ERROR en la tanda de publicación: %s" % e)
                self.env.cr.commit()
                _logger.exception("[forum_partner_import] tanda de publicación fallida")
                return
        if not quedan:
            self._finalizar_publicacion()
            return
        self._encolar_cron()

    def _publicar_tanda(self):
        """Publica una tanda de asientos. Devuelve cuántos quedan pendientes.

        Todo el camino va con el guard del WMS: `_run_fifo` puede escribir el
        `standard_price` del producto y `integracion_wis` engancha ese `write`
        para mandar un request por producto.
        """
        self.ensure_one()
        t0 = time.time()
        Move = self.env["account.move"].sudo().with_context(**CONTEXTO_SIN_WMS)
        asientos = Move.search(self._pub_dominio_borrador(), order="id",
                               limit=self.post_batch_size)
        if not asientos:
            return 0
        publicados, errores = self._pub_postear(asientos)
        self.write({
            "post_done": self.post_done + publicados,
            "post_errors": self.post_errors + errores,
            "post_step": _("Publicando asientos: %d de %d") % (
                self.post_done + publicados, self.post_total),
        })
        _logger.info(
            "[forum_partner_import][batch %s] publicación de %d asientos en %.1fs "
            "(%.1f ms/asiento) | publicados=%d errores=%d",
            self.id, len(asientos), time.time() - t0,
            1000.0 * (time.time() - t0) / len(asientos), publicados, errores)
        # Quedan pendientes si la búsqueda llenó la tanda. NO se recuenta: un
        # `search_count` sobre los borradores cuesta 142 ms (48 ms con el rango)
        # y multiplicado por las miles de tandas eran ~13 minutos de puro
        # conteo. La alternativa `search(limit=1)` es peor todavía: medida en
        # 241 ms, porque sin `order` el planner elige mal.
        return len(asientos) if len(asientos) == self.post_batch_size else 0

    def _pub_postear(self, asientos):
        """`action_post` de la tanda; si falla, asiento por asiento.

        Un asiento que no publica no puede frenar la corrida entera: se reintenta
        solo y, si vuelve a fallar, queda en borrador con el motivo en el log.
        """
        cr = self.env.cr
        try:
            with cr.savepoint():
                asientos.action_post()
                asientos.env.flush_all()
            return len(asientos), 0
        except Exception as e:
            _logger.warning("[forum_partner_import][batch %s] tanda de %d asientos falló "
                            "(%s); se reintenta uno por uno", self.id, len(asientos), e)
        publicados, errores = 0, 0
        for asiento in asientos:
            for intento in range(1, REINTENTOS_ASIENTO + 1):
                try:
                    with cr.savepoint():
                        asiento.action_post()
                        asiento.env.flush_all()
                    publicados += 1
                    break
                except Exception as e:
                    if intento == REINTENTOS_ASIENTO:
                        errores += 1
                        self._log("El asiento %s (id %s) no se pudo publicar: %s"
                                  % (asiento.ref or "-", asiento.id, tools.ustr(e)[:300]))
        return publicados, errores

    def _finalizar_publicacion(self):
        self.ensure_one()
        self.write({"state": "posted", "post_ended_at": fields.Datetime.now(),
                    "post_step": False})
        self._log("Asientos publicados: %d. Errores: %d." % (self.post_done, self.post_errors))
        self.env.cr.commit()
        # Segunda pasada de invariantes: ahora suman los de la publicación.
        try:
            self._verificar_invariantes()
        except Exception as e:
            self.env.cr.rollback()
            self._log("La verificación por invariantes falló: %s" % e)
            _logger.exception("[forum_partner_import] verificación posterior a publicar")
        self.env.cr.commit()

    def _apl_sql_prop_categ(self, prop, categ_sql, cia_sql):
        """Subconsulta escalar que resuelve una propiedad de `product.category`
        con la MISMA precedencia que el ORM.

        `ir.property._get_multi` (`base/models/ir_property.py`) busca con
        `(company_id = X OR company_id IS NULL) AND (res_id IN (...) OR res_id
        IS NULL)`: la fila con `res_id IS NULL` es **el valor por defecto de la
        compañía para todas las categorías**, y la categoría que no tiene fila
        propia se apoya en ella. Exigir fila explícita por categoría corta con
        `UserError` productos que en Odoo valúan perfecto — es lo que pasaba
        acá hasta la 17.0.1.3.2.

        El orden es: fila propia de la categoría antes que el default, y dentro
        de cada nivel la de la compañía antes que la global.

        🔴 La precedencia va por **presencia de fila, no por valor**. Una fila
        explícita con el valor vacío gana igual y deja la cuenta en NULL, que es
        exactamente lo que hace el ORM (devuelve False y corta). Un `coalesce`
        de valores taparía ese caso con el default y crearía el asiento que el
        ORM se niega a crear.

        Se filtra por `fields_id` y no por `ir_property.name`: el nombre solo no
        distingue la propiedad de otro modelo, y en el nivel del default
        (`res_id IS NULL`) no hay `res_id` que desempate.
        """
        campo = ("x.value_text" if prop == "property_valuation"
                 else "split_part(x.value_reference, ',', 2)::int")
        return """(SELECT {campo} FROM ir_property x
                    WHERE x.fields_id = (SELECT f.id FROM ir_model_fields f
                                          WHERE f.model = 'product.category'
                                            AND f.name = '{prop}')
                      AND (x.res_id = 'product.category,' || {categ} OR x.res_id IS NULL)
                      AND (x.company_id = {cia} OR x.company_id IS NULL)
                    ORDER BY (x.res_id IS NULL), (x.company_id IS NULL)
                    LIMIT 1)""".format(campo=campo, prop=prop, categ=categ_sql, cia=cia_sql)

    # Propiedades de la categoría que hacen falta para el asiento, con el alias
    # con el que quedan en `forum_apl_categ`.
    _APL_PROPS_CATEG = (
        ("valuacion", "property_valuation"),
        ("cta_valuacion", "property_stock_valuation_account_id"),
        ("cta_entrada", "property_stock_account_input_categ_id"),
        ("cta_salida", "property_stock_account_output_categ_id"),
        ("diario", "property_stock_journal"),
    )

    def _apl_categ_cuentas(self):
        """Tabla temporal `forum_apl_categ`: las propiedades contables ya
        resueltas para cada par (compañía, categoría) de la tanda.

        Se resuelve una vez por par y no una vez por capa: las categorías son
        cientos y las capas, cientos de miles.
        """
        cr = self.env.cr
        cols = ",\n                   ".join(
            "%s AS %s" % (self._apl_sql_prop_categ(prop, "p.categ_id", "p.company_id"), alias)
            for alias, prop in self._APL_PROPS_CATEG)
        cr.execute("""
            DROP TABLE IF EXISTS forum_apl_categ;
            CREATE TEMP TABLE forum_apl_categ ON COMMIT DROP AS
            WITH pares AS (
                SELECT DISTINCT company_id, categ_id FROM forum_apl WHERE NOT es_cero
            )
            SELECT p.company_id, p.categ_id,
                   {cols}
              FROM pares p
        """.format(cols=cols))
        cr.execute("CREATE INDEX forum_apl_categ_idx ON forum_apl_categ (company_id, categ_id)")
        cr.execute("ANALYZE forum_apl_categ")

    def _apl_asientos(self, params):
        """Asientos de valuación de la tanda, en estado BORRADOR.

        Replica `_validate_accounting_entries` + `_account_entry_move`: **un
        asiento por capa** cuyo producto valúa en tiempo real y cuyo valor no es
        cero, con dos líneas que se cancelan. No se publican acá: eso lo hace la
        fase 3 por el ORM, que es lo que asigna la numeración correlativa del
        diario y corre los hooks. Por eso quedan sin `name`, sin
        `sequence_prefix/number` y sin `posted_before`.

        Cuentas y diario salen de la categoría del producto
        (`_get_accounting_data_for_valuation`), resueltos con la precedencia del
        ORM en `_apl_categ_cuentas`. En una ENTRADA el ORM debita valuación y
        acredita `acc_src`; en una SALIDA debita `acc_dest` y acredita
        valuación.

        Y `acc_src` y `acc_dest` NO son la misma cuenta ni salen de la misma
        punta del movimiento (`stock_account/models/stock_move.py:392`):

        - `_get_src_account` = cuenta de la ubicación de ORIGEN
          (`valuation_out_account_id`) y, si no la tiene, la cuenta de
          **entrada** de la categoría.
        - `_get_dest_account` = cuenta de la ubicación de DESTINO
          (`valuation_in_account_id`) **solo si su uso es `inventory` o
          `production`**, y si no, la cuenta de **salida** de la categoría.

        En una entrada la ubicación de ajuste es el ORIGEN; en una salida, el
        DESTINO. El ORM valida las dos cuentas vaya para donde vaya el
        movimiento, así que acá se exigen las dos igual.

        Los campos que no se ponen acá los cubre `_apl_defaults` con
        `default_get`, así entra lo que agregue cualquier módulo instalado
        (los `cfe_*` de la localización, `extract_state`, etc.).
        """
        cr = self.env.cr
        Move = self.env["account.move"]
        MoveLine = self.env["account.move.line"]
        # Capas de la tanda que generan asiento: producto con valuación en
        # tiempo real y valor distinto de cero. Mismo filtro que el ORM.
        self._apl_categ_cuentas()
        cr.execute("""
            DROP TABLE IF EXISTS forum_apl_asiento;
            CREATE TEMP TABLE forum_apl_asiento ON COMMIT DROP AS
            WITH base AS (
                SELECT a.row_num, a.svl_id, a.move_id, a.company_id, a.product_id,
                       a.diff, a.dec_cia, a.prod_name,
                       l.value AS valor,
                       abs(l.value) AS importe,
                       l.quantity AS cantidad_capa,
                       -- Cotización y moneda de reporte de LA CAPA: las escribe
                       -- este mismo motor al replicar tchistorico, así que
                       -- propagarlas a la línea del asiento no es duplicar una
                       -- fórmula ajena, es reusar un valor propio.
                       l."cotizacionDia" AS cotiz_dia,
                       l.moneda_reporte_id AS moneda_rep,
                       pt.uom_id,
                       c.currency_id,
                       pcat.cta_valuacion,
                       -- `_get_src_account`: la cuenta de la ubicación de
                       -- ORIGEN y, si no la tiene, la de ENTRADA de la
                       -- categoría. En una entrada el origen es la ubicación de
                       -- ajuste; en una salida, la interna.
                       coalesce(CASE WHEN a.diff > 0 THEN li.valuation_out_account_id
                                     ELSE ls.valuation_out_account_id END,
                                pcat.cta_entrada) AS cta_src,
                       -- `_get_dest_account`: la cuenta de la ubicación de
                       -- DESTINO solo si su uso es de ajuste o producción, y si
                       -- no, la de SALIDA de la categoría. En una entrada el
                       -- destino es la interna, que no entra en ese caso.
                       CASE WHEN a.diff > 0 THEN pcat.cta_salida
                            ELSE coalesce(li.valuation_in_account_id, pcat.cta_salida) END
                           AS cta_dest,
                       pcat.diario
                  FROM forum_apl a
                  JOIN stock_valuation_layer l ON l.id = a.svl_id
                  JOIN product_product pp ON pp.id = a.product_id
                  JOIN product_template pt ON pt.id = pp.product_tmpl_id
                  JOIN res_company c ON c.id = a.company_id
                  JOIN stock_location li ON li.id = a.inv_loc
                  JOIN stock_location ls ON ls.id = a.location_id
                  JOIN forum_apl_categ pcat ON pcat.company_id = a.company_id
                                           AND pcat.categ_id = a.categ_id
                 WHERE NOT a.es_cero
                   AND coalesce(pcat.valuacion, 'manual') = 'real_time'
                   AND round(l.value::numeric, a.dec_cia) <> 0
            )
            -- La contrapartida del asiento: en una ENTRADA el ORM acredita
            -- `acc_src`; en una SALIDA debita `acc_dest`.
            SELECT base.*,
                   CASE WHEN diff > 0 THEN cta_src ELSE cta_dest END AS cta_contra
              FROM base
        """)
        cr.execute("SELECT count(*) FROM forum_apl_asiento")
        if not cr.fetchone()[0]:
            return 0
        # Un producto que valúa en tiempo real sin cuentas o sin diario es un
        # error de configuración: el ORM corta con UserError y acá también, en
        # vez de dejar capas con valor sin asiento. Se exigen las CUATRO, y las
        # dos contrapartidas vaya el movimiento para donde vaya, porque
        # `_get_accounting_data_for_valuation` las valida todas antes de saber
        # la dirección.
        falta = ("cta_valuacion IS NULL OR cta_src IS NULL OR cta_dest IS NULL "
                 "OR diario IS NULL")
        cr.execute("SELECT count(*) FROM forum_apl_asiento WHERE " + falta)
        sin_cuentas = cr.fetchone()[0]
        if sin_cuentas:
            # La categoría dice qué hay que configurar; el id de producto, no.
            cr.execute("""
                SELECT DISTINCT pc.complete_name
                  FROM forum_apl_asiento a
                  JOIN product_product pp ON pp.id = a.product_id
                  JOIN product_template pt ON pt.id = pp.product_tmpl_id
                  JOIN product_category pc ON pc.id = pt.categ_id
                 WHERE """ + falta + """
                 ORDER BY 1 LIMIT 5""")
            ejemplos = ", ".join(r[0] for r in cr.fetchall())
            raise UserError(_(
                "%d capas de valuación no tienen cuenta o diario en la categoría de su "
                "producto (ejemplos de categoría: %s). Hay que configurar la cuenta de "
                "valuación, la de entrada, la de salida y el diario de inventario antes "
                "de aplicar, en la categoría o en el valor por defecto de la compañía.")
                % (sin_cuentas, ejemplos))

        # Ids de las secuencias, en el orden de las capas: así el asiento de la
        # primera capa lleva el id más bajo, como en el ORM.
        cr.execute("SELECT row_num FROM forum_apl_asiento ORDER BY svl_id")
        orden = [r[0] for r in cr.fetchall()]
        cr.execute("SELECT nextval('account_move_id_seq') FROM generate_series(1, %s)", (len(orden),))
        ids_am = sorted(r[0] for r in cr.fetchall())
        cr.execute("SELECT nextval('account_move_line_id_seq') FROM generate_series(1, %s)",
                   (2 * len(orden),))
        ids_aml = sorted(r[0] for r in cr.fetchall())
        cr.execute("""
            ALTER TABLE forum_apl_asiento ADD COLUMN am_id int,
                                          ADD COLUMN aml_debito int,
                                          ADD COLUMN aml_credito int
        """)
        cr.execute("""
            UPDATE forum_apl_asiento a SET am_id = m.am, aml_debito = m.d, aml_credito = m.c
              FROM unnest(%s::bigint[], %s::int[], %s::int[], %s::int[]) AS m(row_num, am, d, c)
             WHERE a.row_num = m.row_num
        """, (orden, ids_am, ids_aml[0::2], ids_aml[1::2]))

        # La fecha contable: la del batch si se fijó, y si no la del día, igual
        # que el movimiento (`force_period_date` / `fields.Date.context_today`).
        params = dict(params, fecha_asiento=self.inventory_accounting_date or params["hoy"])

        explicitos_am = {
            "id": "a.am_id", "company_id": "a.company_id", "journal_id": "a.diario",
            "currency_id": "a.currency_id", "date": "%(fecha_asiento)s",
            "state": "'draft'", "move_type": "'entry'", "auto_post": "'no'",
            "ref": "%(nombre_upd)s || ' - ' || a.prod_name",
            "stock_move_id": "a.move_id",
            # Sin partner: `_get_partner_id_for_valuation_lines` sale del picking
            # y un movimiento de inventario no tiene.
            "partner_id": "NULL",
            # 🔴 `posted_before` va en NULL, no en false: el ORM lo deja sin
            # valor y la regla es quedar IDÉNTICOS, aunque un false y un NULL
            # se lean igual desde Python. Acá el que se desviaba era el SQL.
            "name": "'/'", "posted_before": "NULL",
            "create_uid": "%(uid)s", "write_uid": "%(uid)s",
            "create_date": "now() AT TIME ZONE 'UTC'", "write_date": "now() AT TIME ZONE 'UTC'",
        }
        # 🔴 Importes de la CABECERA. Son campos calculados-almacenados: el
        # INSERT crudo nunca los computa y quedan en NULL, que Odoo dibuja como
        # `0,00 $`. Publicar los recalcula, así que el hueco sólo se ve MIENTRAS
        # ESTÁN EN BORRADOR — justo la pantalla en la que el cliente revisa
        # antes de publicar, y ahí parecen asientos vacíos aunque sus líneas
        # tengan los importes correctos. No lo cazó la paridad porque la gemela
        # del ORM publica sola y se comparó contra asientos ya publicados.
        #
        # Para un asiento misceláneo el core suma SOLO las líneas de débito
        # (`account/models/account_move.py::_compute_amount`, rama
        # «Miscellaneous journal entry») y `direction_sign` vale 1, así que de
        # los nueve campos sólo tres llevan el importe y seis van en cero.
        # Verificado campo a campo contra 7.342 asientos hechos por el ORM.
        amt = lambda campo, expr: self._apl_num("account.move", campo, expr)
        explicitos_am.update({
            "amount_total": amt("amount_total", "a.importe"),
            "amount_total_signed": amt("amount_total_signed", "a.importe"),
            "amount_total_in_currency_signed": amt("amount_total_in_currency_signed",
                                                   "a.importe"),
            "amount_untaxed": amt("amount_untaxed", "0"),
            "amount_tax": amt("amount_tax", "0"),
            "amount_residual": amt("amount_residual", "0"),
            "amount_untaxed_signed": amt("amount_untaxed_signed", "0"),
            "amount_tax_signed": amt("amount_tax_signed", "0"),
            "amount_residual_signed": amt("amount_residual_signed", "0"),
        })
        if "invoice_date" in Move._fields:
            # La localización le pone default de hoy a TODO asiento, incluidos
            # los manuales; se replica para que la paridad no se vaya por acá.
            explicitos_am["invoice_date"] = "%(fecha_asiento)s"
        # Resto de campos calculados-almacenados de la cabecera. Los pone el ORM
        # al crear y el INSERT crudo los dejaba en NULL; la lista salió del arnés
        # de paridad en modo borrador (`tools/paridad_inventario`). Se filtran
        # por existencia porque varios los agrega la localización y no están en
        # todas las bases.
        #
        # Los de LocalizACIÓN que sí son un cálculo de verdad —no una
        # constante— NO se replican acá: los computa el ORM después del INSERT
        # (ver `_apl_recalcular_localizacion`). Mismo criterio que dejar la
        # publicación en manos del ORM: no se duplica una fórmula cuyo dueño es
        # otro módulo.
        constantes_am = {
            "always_tax_exigible": "true",
            "depreciation_value": "0",
            "extract_state_processed": "false",
            "is_in_extractable_state": "false",
            "is_storno": "false",
            "metodoUnico": "false",
            "payment_distribution_complete": "false",
            "payment_state": "'not_paid'",
            "sequence_number": "0",
            "sequence_prefix": "''",
            "uy_nc_tc_forzado": "0",
            "invoice_date_due": "%(fecha_asiento)s",
        }
        explicitos_am.update({c: v for c, v in constantes_am.items() if c in Move._fields})
        cols_d, vals_d, params_d = self._apl_defaults("account.move", explicitos_am)
        params.update(params_d)
        cr.execute("""
            INSERT INTO account_move ({cols})
            SELECT {vals} FROM forum_apl_asiento a ORDER BY a.am_id
        """.format(cols=", ".join(['"%s"' % c for c in explicitos_am] + cols_d),
                   vals=", ".join(list(explicitos_am.values()) + vals_d)), params)

        # Las dos líneas. En account.move.line casi todo lo que importa es
        # compute/related stored (account_id, balance, debit, credit, date,
        # name, quantity...), así que NO lo cubre default_get: va explícito.
        # `quantity` lleva el signo de la capa en las DOS líneas, como el ORM.
        aml = lambda campo, expr, moneda="dec_cia": self._apl_num(
            "account.move.line", campo, expr, moneda)
        lineas = []
        for lado in ("debito", "credito"):
            signo = "" if lado == "debito" else "-"
            # ENTRADA: debita valuación, acredita la contrapartida.
            # SALIDA: al revés. El signo del valor de la capa ya lo dice.
            cuenta = ("CASE WHEN a.diff > 0 THEN a.cta_valuacion ELSE a.cta_contra END"
                      if lado == "debito" else
                      "CASE WHEN a.diff > 0 THEN a.cta_contra ELSE a.cta_valuacion END")
            explicitos_aml = {
                "id": "a.aml_%s" % lado,
                "move_id": "a.am_id", "company_id": "a.company_id",
                "account_id": cuenta,
                "name": "%(nombre_upd)s || ' - ' || a.prod_name",
                "ref": "%(nombre_upd)s || ' - ' || a.prod_name",
                "date": "%(fecha_asiento)s",
                "parent_state": "'draft'", "display_type": "'product'",
                "currency_id": "a.currency_id", "company_currency_id": "a.currency_id",
                "product_id": "a.product_id", "product_uom_id": "a.uom_id",
                "quantity": aml("quantity", "a.cantidad_capa"),
                "debit": aml("debit", "a.importe" if lado == "debito" else "0"),
                "credit": aml("credit", "a.importe" if lado == "credito" else "0"),
                "balance": aml("balance", "%sa.importe" % signo),
                "amount_currency": aml("amount_currency", "%sa.importe" % signo),
                "partner_id": "NULL", "sequence": "100",
                "create_uid": "%(uid)s", "write_uid": "%(uid)s",
                "create_date": "now() AT TIME ZONE 'UTC'", "write_date": "now() AT TIME ZONE 'UTC'",
            }
            # Resto de calculados-almacenados de la LÍNEA, también salidos del
            # arnés en modo borrador. `journal_id` y `account_root_id` no son
            # cosmética: son `related` almacenados que usan filtros e informes,
            # y estaban en NULL.
            constantes_aml = {
                "journal_id": "a.diario",
                "move_name": "'/'",
                "account_root_id": ("(SELECT ac.root_id FROM account_account ac "
                                    "WHERE ac.id = %s)" % cuenta),
                "price_subtotal": "0",
                "price_total": "0",
                "price_unit": "0",
                "reconciled": "false",
                "tax_tag_invert": "false",
                # 🔴 En la LÍNEA estos dos no tienen `compute`: los escribe el
                # `create()` de `tchistorico` (`general_primate`), así que el
                # ORM no los puede calcular a pedido y hay que ponerlos acá.
                # La fórmula es la de ese módulo: la cotización de la capa, y el
                # importe convertido. Sin moneda de reporte, ambos en cero.
                # El promedio ponderado de la CABECERA sí lo computa el ORM
                # desde estas líneas: por eso da distinto (0,025068 contra
                # 0,025083) y por eso no se replica.
                "cotizacion_historica": (
                    "CASE WHEN a.moneda_rep IS NOT NULL THEN a.cotiz_dia ELSE 0 END"),
                "valor_moneda_reportes": aml(
                    "valor_moneda_reportes",
                    "CASE WHEN a.moneda_rep IS NOT NULL "
                    "THEN a.importe * a.cotiz_dia ELSE 0 END"),
                "cfe_no_send_description": "false",
                "invoice_date": "%(fecha_asiento)s",
            }
            explicitos_aml.update({c: v for c, v in constantes_aml.items()
                                   if c in MoveLine._fields})
            cols_l, vals_l, params_l = self._apl_defaults("account.move.line", explicitos_aml)
            params.update(params_l)
            lineas.append((explicitos_aml, cols_l, vals_l))
        for explicitos_aml, cols_l, vals_l in lineas:
            cr.execute("""
                INSERT INTO account_move_line ({cols})
                SELECT {vals} FROM forum_apl_asiento a ORDER BY a.am_id
            """.format(cols=", ".join(['"%s"' % c for c in explicitos_aml] + cols_l),
                       vals=", ".join(list(explicitos_aml.values()) + vals_l)), params)

        cr.execute("""
            UPDATE stock_valuation_layer l SET account_move_id = a.am_id
              FROM forum_apl_asiento a WHERE l.id = a.svl_id
        """)
        cr.execute("SELECT count(*) FROM forum_apl_asiento")
        creados = cr.fetchone()[0]
        for modelo in ("account.move", "account.move.line"):
            self.env[modelo].invalidate_model()
        return creados

    # Campos calculados-almacenados que NO se replican en SQL: son cálculos de
    # verdad —no constantes— y su dueño es otro módulo (la localización). El
    # criterio es el mismo por el que la publicación se dejó en manos del ORM:
    # duplicar una fórmula ajena es firmar que va a driftear en silencio con el
    # próximo cambio de `LocalizacionUy`. Que `cotizacion_historica` valga
    # distinto en la cabecera (0,025068) y en la línea (0,025083) del MISMO
    # asiento es la prueba de que no es una constante disfrazada.
    _CAMPOS_POR_ORM = {
        "account.move": ("cotizacion_historica", "moneda_reportes_id",
                         "valor_moneda_reportes",
                         # Del core, pero tampoco es constante: sale de una
                         # cadena TRADUCIDA y del nombre de quien creó.
                         "invoice_partner_display_name"),
        # El quant NO se crea, se actualiza, así que el INSERT no lo toca y se
        # quedaba con el valor de reporte VIEJO: el compute depende de las capas
        # del producto, que esta tanda acaba de cambiar. `_compute_value_report`
        # escribe también `unit_value_report`, por eso alcanza con pedir uno.
        "stock.quant": ("value_report",),
        "account.move.line": ("tipo_cambio", "amount_secondary",
                              # 🔴 Parecían constantes en cero y NO lo son: el
                              # arnés mostró líneas con 0 y líneas con el saldo,
                              # según si la cuenta es conciliable.
                              "amount_residual", "amount_residual_currency"),
    }

    def _apl_recalcular_localizacion(self):
        """Deja que el ORM calcule los campos de la localización de la tanda.

        Se hace sobre los asientos que acaba de crear el INSERT y **acotado a
        esos campos**: no es un recompute general, que costaría como el camino
        ORM que este motor justamente evita.
        """
        # 🔴 Como el usuario del proceso, no como el de la sesión: el flush
        # escribe, y escribir deja `write_uid`. Corriéndolo con el usuario
        # equivocado la réplica se desviaba del ORM en ese campo —lo encontró
        # el arnés de paridad, que es exactamente para esto—.
        env = self.env(user=self.inventory_user_id or self.env.user)
        cr = env.cr
        cr.execute("SELECT to_regclass('forum_apl_asiento') IS NOT NULL")
        hay_asientos = cr.fetchone()[0]
        ids_am, ids_aml = [], []
        if hay_asientos:
            cr.execute("SELECT am_id FROM forum_apl_asiento")
            ids_am = [r[0] for r in cr.fetchall()]
            cr.execute("SELECT aml_debito FROM forum_apl_asiento "
                       "UNION ALL SELECT aml_credito FROM forum_apl_asiento")
            ids_aml = [r[0] for r in cr.fetchall()]
        cr.execute("SELECT quant_id FROM forum_apl WHERE quant_id IS NOT NULL")
        ids_quant = [r[0] for r in cr.fetchall()]

        for modelo, ids in (("account.move", ids_am), ("account.move.line", ids_aml),
                            ("stock.quant", ids_quant)):
            Modelo = env[modelo]
            campos = [Modelo._fields[c] for c in self._CAMPOS_POR_ORM[modelo]
                      if c in Modelo._fields and Modelo._fields[c].compute
                      and Modelo._fields[c].store]
            if not campos:
                continue
            registros = Modelo.browse(ids)
            for campo in campos:
                env.add_to_compute(campo, registros)
        env.flush_all()
        # El flush deja la caché del ORM con estos registros; invalidarla evita
        # que una tanda posterior lea valores viejos.
        for modelo in self._CAMPOS_POR_ORM:
            env[modelo].invalidate_model()

    def _apl_fifo_valores(self, params):
        """Reparto FIFO de las salidas de la tanda, como lo hace `_run_fifo`.

        Deja en `forum_apl`, por cada celda con salida:

        `faltante` es la cantidad que las capas con saldo no alcanzan a cubrir
        (caso de stock negativo). `val_salida` es el `value` de su capa,
        negativo: la suma de lo tomado de cada capa candidata, redondeando cada
        toma por separado (el ORM hace `currency.round(value_taken_on_candidate)`
        dentro del bucle), más el faltante valuado al último costo conocido.
        `costo_salida` es el `unit_cost` de la capa, que en una salida FIFO es
        `tmp_value / cantidad` y no el costo del producto.

        El reparto se hace por rangos: cada salida ocupa el tramo
        `[antes, antes + cantidad)` del total a consumir del producto, cada capa
        candidata ocupa su propio tramo en el orden `create_date, id` (el `_order`
        del modelo, que es el que usa `_get_fifo_candidates`), y lo que cada
        salida toma de cada capa es el solapamiento de los dos tramos. Así se
        replica el bucle del ORM sin iterar fila por fila.

        Deja también la tabla temporal `forum_apl_toma`, que usa el UPDATE del
        consumo para descontar `remaining_qty` y `remaining_value` de cada capa.
        """
        cr = self.env.cr
        cr.execute("DROP TABLE IF EXISTS forum_apl_toma")
        cr.execute("""
            CREATE TEMP TABLE forum_apl_toma ON COMMIT DROP AS
            WITH salidas AS (
                SELECT row_num, product_id, company_id, dec_cia, costo, -diff AS cantidad,
                       sum(-diff) OVER (PARTITION BY product_id, company_id
                                        ORDER BY move_id) - (-diff) AS antes,
                       sum(-diff) OVER (PARTITION BY product_id, company_id
                                        ORDER BY move_id) AS hasta
                  FROM forum_apl WHERE diff < 0 AND NOT es_cero
            ),
            candidatas AS (
                SELECT l.id, l.product_id, l.company_id, l.remaining_qty,
                       -- Costo unitario de la capa: remaining_value/remaining_qty,
                       -- como `candidate_unit_cost` del ORM (no su unit_cost).
                       coalesce(l.remaining_value, 0) / nullif(l.remaining_qty, 0) AS costo,
                       sum(l.remaining_qty) OVER (PARTITION BY l.product_id, l.company_id
                                                  ORDER BY l.create_date, l.id)
                           - l.remaining_qty AS antes,
                       sum(l.remaining_qty) OVER (PARTITION BY l.product_id, l.company_id
                                                  ORDER BY l.create_date, l.id) AS hasta,
                       row_number() OVER (PARTITION BY l.product_id, l.company_id
                                          ORDER BY l.create_date DESC, l.id DESC) AS ultima
                  FROM stock_valuation_layer l
                 WHERE l.remaining_qty > 0
                   AND (l.product_id, l.company_id) IN (SELECT product_id, company_id FROM salidas)
            )
            SELECT s.row_num, s.product_id, s.company_id, c.id AS capa_id,
                   least(s.hasta, c.hasta) - greatest(s.antes, c.antes) AS toma,
                   c.costo AS costo_capa,
                   -- Cada toma se redondea por separado, como en el bucle del ORM.
                   round(((least(s.hasta, c.hasta) - greatest(s.antes, c.antes)) * c.costo)::numeric,
                         s.dec_cia) AS valor_tomado
              FROM salidas s
              JOIN candidatas c ON c.product_id = s.product_id AND c.company_id = s.company_id
             WHERE least(s.hasta, c.hasta) > greatest(s.antes, c.antes)
        """)
        cr.execute("CREATE INDEX forum_apl_toma_idx ON forum_apl_toma (row_num)")
        cr.execute("CREATE INDEX forum_apl_toma_capa ON forum_apl_toma (capa_id)")
        cr.execute("ANALYZE forum_apl_toma")

        # Faltante y valores de cada salida. `last_fifo_price` del ORM es el
        # costo de la última capa que alcanzó a mirar; si no había ninguna, cae
        # en el `standard_price` del producto.
        cr.execute("""
            WITH disp AS (
                SELECT product_id, company_id, sum(remaining_qty) AS saldo,
                       -- `last_fifo_price` del ORM es el costo de la ÚLTIMA capa
                       -- candidata que alcanzó a mirar, AUNQUE SEA 0. Solo cuando
                       -- no hubo ninguna candidata cae en el standard_price del
                       -- producto. Verificado: con una candidata de
                       -- remaining_value=0, el ORM valuó la salida en 0 y un
                       -- `nullif(costo, 0)` la valuaba al costo del producto.
                       count(*) AS candidatas,
                       (array_agg(costo ORDER BY create_date DESC, id DESC))[1] AS costo_ultima
                  FROM (SELECT l.product_id, l.company_id, l.remaining_qty, l.create_date, l.id,
                               coalesce(l.remaining_value, 0) / nullif(l.remaining_qty, 0) AS costo
                          FROM stock_valuation_layer l
                         WHERE l.remaining_qty > 0
                           AND (l.product_id, l.company_id) IN
                               (SELECT product_id, company_id FROM forum_apl
                                 WHERE diff < 0 AND NOT es_cero)) x
                 GROUP BY 1, 2
            ),
            salidas AS (
                SELECT row_num, product_id, company_id, -diff AS cantidad,
                       sum(-diff) OVER (PARTITION BY product_id, company_id
                                        ORDER BY move_id) - (-diff) AS antes,
                       sum(-diff) OVER (PARTITION BY product_id, company_id
                                        ORDER BY move_id) AS hasta
                  FROM forum_apl WHERE diff < 0 AND NOT es_cero
            ),
            tomado AS (
                SELECT row_num, sum(valor_tomado) AS valor FROM forum_apl_toma GROUP BY 1
            )
            UPDATE forum_apl a SET
                -- Lo que de esta salida queda sin cubrir por capas con saldo.
                faltante = greatest(0, least(s.cantidad,
                                             s.hasta - coalesce(d.saldo, 0))),
                -- `last_fifo_price` del ORM: `new_standard_price or standard_price`.
                -- `new_standard_price` es el costo de la última candidata mirada,
                -- y en Python un 0.0 es falsy, así que con candidatas de costo 0
                -- el ORM TAMBIÉN cae en el standard_price. El `nullif` replica
                -- ese `or`. Verificado simulando `_run_fifo` sobre un caso real:
                -- candidata de rem_val=0 y faltante 1 → value=-2875, unit_cost=2875.
                val_salida = -(coalesce(t.valor, 0)
                               + greatest(0, least(s.cantidad, s.hasta - coalesce(d.saldo, 0)))
                                 * coalesce(nullif(d.costo_ultima, 0), a.costo)),
                costo_salida = CASE WHEN s.cantidad = 0 THEN 0 ELSE
                    (coalesce(t.valor, 0)
                     + greatest(0, least(s.cantidad, s.hasta - coalesce(d.saldo, 0)))
                       * coalesce(nullif(d.costo_ultima, 0), a.costo)) / s.cantidad END
              FROM salidas s
              LEFT JOIN disp d ON d.product_id = s.product_id AND d.company_id = s.company_id
              LEFT JOIN tomado t ON t.row_num = s.row_num
             WHERE a.row_num = s.row_num
        """)

    def _apl_sql_cotiz(self):
        """Expresión SQL de la cotización de la moneda de reporte a la fecha.

        Replica `res.currency._get_conversion_rate(moneda_cía, monedaDeReporte)`,
        que es lo que usa el `create()` de tchistorico: el cociente entre la
        tasa de la moneda destino y la de la moneda origen, cada una la última
        cargada con fecha menor o igual. Verificado contra el ORM en la copia:
        el ORM devolvió 0.025082773151399618 y el SQL (0.025082773151399618 / 1.0).

        Devuelve `NULL::numeric` si la compañía no tiene moneda de reporte; ahí
        tchistorico deja sus campos en 0 (rama `else` de su override).
        """
        if "monedaDeReporte" not in self.env["res.company"]._fields:
            return "NULL::numeric"
        tasa = """(SELECT r.rate FROM res_currency_rate r
                    WHERE r.currency_id = %s AND r.name <= %%(hoy)s
                      AND (r.company_id = c.id OR r.company_id IS NULL)
                    ORDER BY r.name DESC, r.company_id NULLS LAST LIMIT 1)"""
        return ("(%s / nullif(%s, 0))"
                % (tasa % 'c."monedaDeReporte"', tasa % "c.currency_id"))

    def _apl_tchistorico(self, Layer, capa, val_entrada):
        """Campos que tchistorico calcularía en el `create()` de la capa.

        El INSERT por SQL no pasa por ese `create()`, así que sus campos se
        replican acá con la misma fórmula. Su rama de entrada (`value > 0`)
        exige cotización y **levanta UserError si no la encuentra**; la de
        salida (`value < 0`) la tolera y deja todo en 0. El SQL no puede
        levantar ese error, así que cuando no hay cotización deja los campos en
        0 y `moneda_reporte_id` en NULL, que es exactamente la rama `else` del
        módulo: el dato es de reporte, no de stock ni de contabilidad.

        `a.cotiz` es la cotización de la moneda de reporte a la fecha, que
        `_apl_sql` deja en la tabla de trabajo (equivale a
        `res.currency._get_conversion_rate(moneda_cía, monedaDeReporte)`).
        """
        if "moneda_reporte_id" not in Layer._fields:
            return {}
        # La condición NO es "hay cotización": es el VALOR de la capa. El
        # `create()` de tchistorico entra por su rama de entrada con `value > 0`,
        # por la de salida con `value < 0`, y **todo lo demás —incluido
        # `value = 0`— cae en el `else`**, que deja `cotizacionDia` en 0,
        # `moneda_reporte_id` en NULL y los cuatro campos de costo destino SIN
        # ASIGNAR (o sea NULL, no 0).
        # Verificado contra la gemela ORM: de 12.610 capas de valor 0, el ORM
        # dejó las 12.610 con esos campos en NULL y ninguna con cotización;
        # esta réplica escribía 66 con cotización porque miraba `a.cotiz`.
        # 🔴 Por el signo CRUDO del valor, sin redondear. `tchistorico` ramifica
        # con `vals.get('value', 0) > 0` y `< 0` (models.py:199 y :224), y el
        # valor que recibe es el mismo que guardamos. Redondear antes de decidir
        # es INTERPRETAR en vez de replicar: una salida de -0,004, que existe y
        # es negativa, caía en el `else` de la réplica y en la rama de salida del
        # ORM, y la capa quedaba sin `moneda_reporte_id`. Lo destapó el arnés al
        # subir la muestra a 12 celdas. Manda el ORM.
        valor_no_cero = ("(CASE WHEN a.diff > 0 THEN (%s) ELSE a.val_salida END) <> 0"
                         % val_entrada)
        con_cotiz = "a.cotiz IS NOT NULL AND a.cotiz <> 0 AND " + valor_no_cero
        # El valor de la capa, ya con signo: entrada positiva, salida negativa.
        valor = "CASE WHEN a.diff > 0 THEN (%s) ELSE a.val_salida END" % val_entrada
        costo = "CASE WHEN a.diff > 0 THEN a.costo ELSE a.costo_salida END"
        # `valorRestante` de tchistorico es `remaining_value * cotización`, y el
        # remaining_value de una SALIDA queda NULL/0 siempre (ver el INSERT de
        # capas): así que en una salida este campo es 0, también con faltante.
        restante = "CASE WHEN a.diff > 0 THEN (%s) ELSE 0 END" % val_entrada
        # cantidad_svl del módulo: usa 1 si la cantidad es 0, para no dividir por cero.
        cantidad = "CASE WHEN a.diff = 0 THEN 1 ELSE a.diff END"
        formulas = {
            # 🔴 SIEMPRE la moneda de la compañía, sin condición. La rama `else`
            # de tchistorico escribe `moneda_reporte_id: False`, pero el campo es
            # un **related almacenado** de `company_id.monedaDeReporte`
            # (models.py:31) y el ORM lo recomputa después: gana el related, no
            # el `create`. Verificado sobre una capa de valor exactamente 0, con
            # `cotizacionDia` en 0 en los dos caminos y la moneda puesta sólo por
            # el ORM. La condición vieja replicaba lo que el `create` escribe y
            # no lo que la base termina teniendo.
            "moneda_reporte_id": 'c."monedaDeReporte"',
            "cotizacionDia": ("cotizacionDia", "a.cotiz"),
            "valorMonedaSecundaria": ("valorMonedaSecundaria", "(%s) * a.cotiz" % valor),
            "valorRestante": ("valorRestante", "(%s) * a.cotiz" % restante),
            "valorUnitario": ("valorUnitario", "(%s) * a.cotiz" % costo),
            # En una ENTRADA es value/cantidad; en una SALIDA es el value pelado.
            "unitCostesDestinoInc": ("unitCostesDestinoInc",
                                     "CASE WHEN a.diff > 0 THEN (%s) / (%s) ELSE a.val_salida END"
                                     % (val_entrada, cantidad)),
            "unitCostesDestinoIncMR": ("unitCostesDestinoIncMR",
                                       "CASE WHEN a.diff > 0 THEN (%s) * a.cotiz / (%s) "
                                       "ELSE a.val_salida * a.cotiz END"
                                       % (val_entrada, cantidad)),
            "valorizadoCosteDestino": ("valorizadoCosteDestino", valor),
            "valorizadoCosteDestinoMR": ("valorizadoCosteDestinoMR", "(%s) * a.cotiz" % valor),
            # ucmr y unit_cost_report se asignan SIEMPRE, incluso sin cotización:
            # el módulo hace `vals['ucmr'] = unit_cost * vals.get('cotizacionDia', 1.0)`
            # fuera del if, y con cotizacionDia en 0 el producto queda en 0.
            "ucmr": ("ucmr", "(%s) * coalesce(a.cotiz, 0)" % costo),
            # `unit_cost_report` es el único CALCULADO de tchistorico, y el ORM
            # lo computa DESPUÉS de guardar `cotizacionDia`, o sea desde el
            # valor ya redondeado a sus 6 decimales, no desde la tasa completa.
            # La diferencia es visible: 3556 × 0,025083 = 89,195148 → 89,20,
            # mientras 3556 × 0,025082773… = 89,19434 → 89,19. La paridad contra
            # la gemela ORM lo detectó en 78 capas.
            "unit_cost_report": ("unit_cost_report",
                                 "(%s) * coalesce(nullif(round(a.cotiz, 6), 0), 1)" % costo),
        }
        # Estos cuatro solo se asignan en las ramas CON cotización; en el `else`
        # el módulo no los toca, así que quedan NULL (no 0).
        solo_con_cotiz = ("unitCostesDestinoInc", "unitCostesDestinoIncMR",
                          "valorizadoCosteDestino", "valorizadoCosteDestinoMR")
        salida = {}
        for campo, formula in formulas.items():
            if campo not in Layer._fields:
                continue
            if campo == "moneda_reporte_id":
                salida[campo] = formula
                continue
            nombre, expr = formula
            if campo in solo_con_cotiz:
                moneda = "dec_rep" if Layer._fields[campo].type == "monetary" else "dec_cia"
                salida[campo] = "CASE WHEN %s THEN %s ELSE NULL END" % (
                    con_cotiz, capa(nombre, expr, moneda))
                continue
            # Los Monetary de tchistorico redondean por `moneda_reporte_id`, que
            # el ORM deja en NULL cuando no hay cotización: ahí no redondea.
            moneda = "dec_rep" if Layer._fields[campo].type == "monetary" else "dec_cia"
            if campo in ("ucmr", "unit_cost_report"):
                # Se asignan siempre: no van dentro del CASE de cotización.
                salida[campo] = capa(nombre, expr, moneda)
                continue
            salida[campo] = "CASE WHEN %s THEN %s ELSE %s END" % (
                con_cotiz, capa(nombre, expr, moneda), capa(nombre, "0", None))
        return salida

    def _apl_num(self, modelo, campo, expr, moneda="dec_cia"):
        """Expresión SQL de un numérico con la misma escala que guarda el ORM.

        El ORM no guarda el número tal cual: un Float con `digits` va redondeado
        y con esa escala (`6.00`), un Monetary con los decimales de su moneda si
        la tiene, y un Float sin dígitos como un float de Python (`6.0`). El
        valor es el mismo, pero la paridad con el ORM se exige exacta.
        `moneda` es la columna de forum_apl con los decimales, o None si el ORM
        no tiene moneda al guardar.
        """
        definicion = self.env[modelo]._fields.get(campo)
        if definicion is None:
            return expr
        if definicion.type == "monetary" and moneda:
            return "round((%s)::numeric, a.%s)" % (expr, moneda)
        if definicion.type in ("float", "monetary"):
            digitos = definicion.get_digits(self.env) if definicion.type == "float" else None
            if digitos:
                return "round((%s)::numeric, %d)" % (expr, digitos[1])
            return ("(CASE WHEN (%s) = trunc(%s) THEN round((%s)::numeric, 1) "
                    "ELSE (%s)::numeric END)" % (expr, expr, expr, expr))
        return expr

    def _apl_valores(self, columna):
        self.env.cr.execute("SELECT DISTINCT %s FROM forum_apl" % columna)
        return [r[0] for r in self.env.cr.fetchall()]

    # ------------------------------------------------------------------
    # Camino ORM (híbrido)
    # ------------------------------------------------------------------
    def _apl_orm(self, t, filas, resultado, errores):
        """`_apply_inventory` sobre las celdas de productos con valuación.

        Todas pasan por el ORM, también las de diferencia 0: Odoo les crea el
        movimiento de cantidad 0. Si la tanda falla entera, se reintenta quant
        por quant con savepoint.
        """
        cr = self.env.cr
        Quant = self.env["stock.quant"].with_user(self.inventory_user_id)
        cr.execute("""
            SELECT row_num, product_id, location_id, company_id, cantidad
              FROM {t} WHERE row_num = ANY(%s)
        """.format(t=t), (filas,))
        datos = {r[0]: r for r in cr.fetchall()}

        quant_de_fila = self._apl_bloquear_quants(t, filas)
        for fila in filas:
            _r, product_id, location_id, company_id, cantidad = datos[fila]
            if fila in quant_de_fila:
                continue
            if not cantidad:
                resultado[fila] = "sin_diferencia"
                continue
            try:
                with cr.savepoint():
                    quant = Quant.with_company(company_id).with_context(inventory_mode=True).create({
                        "product_id": product_id, "location_id": location_id,
                        "inventory_quantity": float(cantidad),
                    })
                    Quant.env.flush_all()
                quant_de_fila[fila] = quant.id
            except Exception as e:
                resultado[fila] = "error"
                errores[fila] = tools.ustr(e)[:1000]

        sin_diferencia = self._apl_poner_contado(t, quant_de_fila)
        self.env["stock.quant"].invalidate_model()

        por_compania = {}
        for fila in filas:
            if fila in quant_de_fila:
                por_compania.setdefault(datos[fila][3], []).append((fila, quant_de_fila[fila]))
        for company_id, pares in por_compania.items():
            ok, fallidos = self._apl_aplicar(Quant.with_company(company_id), pares)
            for fila in ok:
                resultado[fila] = "sin_diferencia" if fila in sin_diferencia else "aplicado"
            for fila, mensaje in fallidos.items():
                resultado[fila] = "error"
                errores[fila] = mensaje

    def _apl_bloquear_quants(self, t, filas):
        """{row_num: quant_id} de las celdas, con los quants bloqueados.

        Si un par tiene más de un quant, se fusionan con el método del core antes
        de seguir: ajustar uno solo dejaría el total distinto del contado.
        """
        cr = self.env.cr
        consulta = """
            SELECT s.row_num, q.id
              FROM {t} s
              JOIN stock_quant q ON q.product_id = s.product_id AND q.location_id = s.location_id
             WHERE s.row_num = ANY(%s)
               AND q.lot_id IS NULL AND q.package_id IS NULL AND q.owner_id IS NULL
             ORDER BY q.id
               FOR NO KEY UPDATE OF q
        """.format(t=t)
        cr.execute(consulta, (filas,))
        vistos = {}
        for fila, quant_id in cr.fetchall():
            vistos.setdefault(fila, []).append(quant_id)
        duplicados = [q for ids in vistos.values() if len(ids) > 1 for q in ids]
        if duplicados:
            self.env["stock.quant"].sudo().browse(duplicados)._merge_quants()
            cr.execute(consulta, (filas,))
            vistos = {}
            for fila, quant_id in cr.fetchall():
                vistos.setdefault(fila, []).append(quant_id)
        return {fila: min(ids) for fila, ids in vistos.items()}

    def _apl_poner_contado(self, t, quant_de_fila):
        """Pone el contado recalculando la diferencia. Devuelve las filas sin diferencia."""
        if not quant_de_fila:
            return set()
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
            RETURNING m.row_num,
                      abs(q.inventory_diff_quantity) < (
                          SELECT u.rounding / 2 FROM product_product pp
                            JOIN product_template pt ON pt.id = pp.product_tmpl_id
                            JOIN uom_uom u ON u.id = pt.uom_id
                           WHERE pp.id = q.product_id)
        """.format(t=t, reason=", reason = %(reason)s" if tiene_reason else ""), {
            "filas": filas_q, "quants": [quant_de_fila[r] for r in filas_q],
            "usuario": self.inventory_user_id.id, "uid": self.inventory_user_id.id,
            "fecha": self.inventory_accounting_date or None,
            "reason": self.inventory_reason,
        })
        return {fila for fila, sin_diferencia in cr.fetchall() if sin_diferencia}

    def _apl_aplicar(self, Quant, pares):
        """`_apply_inventory` de la tanda; si falla, uno por uno.

        Devuelve (filas aplicadas, {fila: mensaje de error}).
        """
        cr = self.env.cr
        ids = [quant_id for _r, quant_id in pares]
        # El flush va adentro del savepoint y con el entorno del responsable:
        # el que hace el savepoint al cerrar usa el entorno raíz de la
        # transacción (el del cron) y deja write_uid con otro usuario.
        try:
            with cr.savepoint():
                Quant.browse(ids)._apply_inventory()
                Quant.env.flush_all()
            return [fila for fila, _q in pares], {}
        except Exception as e:
            _logger.warning("[forum_partner_import][batch %s] tanda ORM de %d quants falló (%s); "
                            "se reintenta uno por uno", self.id, len(ids), e)

        ok, fallidos = [], {}
        for fila, quant_id in pares:
            try:
                with cr.savepoint():
                    Quant.browse(quant_id)._apply_inventory()
                    Quant.env.flush_all()
                ok.append(fila)
            except Exception as e:
                fallidos[fila] = tools.ustr(e)[:1000]
        return ok, fallidos

    # ==================================================================
    # Cierre: recálculos que el ORM habría disparado
    # ==================================================================
    def _apl_recalculos_finales(self, productos, desde, commit=True):
        """Replica las cascadas del ORM sobre los productos aplicados por SQL.

        - `stock.quant.value_report` / `unit_value_report` (tchistorico): por
          SQL, con la misma fórmula del compute (suma de `valorRestante` y
          `remaining_qty` de las capas del producto con valorUnitario,
          valorRestante y remaining_qty positivos, redondeado a la moneda de
          reportes). Por el ORM serían ~850.000 búsquedas.
        - `product.product.ultimo_costo_mr` y el de la plantilla (tchistorico):
          por el ORM, un compute por producto.
        - `stock.warehouse.orderpoint.qty_to_order`: por el ORM.
        """
        productos = sorted(set(productos))
        if not productos:
            return
        cr = self.env.cr
        uid = self.inventory_user_id.id
        Quant = self.env["stock.quant"]
        pasos = [productos[i:i + PASO_RECALCULO] for i in range(0, len(productos), PASO_RECALCULO)]

        if "value_report" in Quant._fields:
            for n, tramo in enumerate(pasos, start=1):
                self._apl_etapa(_("Valor de reporte de los quants (%d/%d)") % (n, len(pasos)), commit)
                cr.execute("""
                    WITH capas AS (
                        SELECT product_id, company_id,
                               sum("valorRestante") AS valor, sum(remaining_qty) AS cantidad
                          FROM stock_valuation_layer
                         WHERE product_id = ANY(%(prod)s)
                           AND "valorUnitario" > 0 AND "valorRestante" > 0 AND remaining_qty > 0
                         GROUP BY 1, 2
                    )
                    UPDATE stock_quant q SET
                        -- Field.write no reescribe un valor igual: se conserva el guardado.
                        value_report = CASE
                            WHEN q2.value_report = round(coalesce(c.valor, 0), coalesce(cur.decimal_places, 2))
                            THEN q2.value_report
                            ELSE round(coalesce(c.valor, 0), coalesce(cur.decimal_places, 2)) END,
                        -- NULL en los quants creados por esta aplicación, como deja el ORM
                        unit_value_report = CASE
                            WHEN q2.unit_value_report IS NULL AND q2.create_date >= %(desde)s THEN NULL
                            WHEN q2.unit_value_report = CASE WHEN coalesce(c.cantidad, 0) > 0
                                 THEN round(c.valor / c.cantidad, coalesce(cur.decimal_places, 2)) ELSE 0 END
                            THEN q2.unit_value_report
                            WHEN coalesce(c.cantidad, 0) > 0
                            THEN round(c.valor / c.cantidad, coalesce(cur.decimal_places, 2))
                            ELSE round(0, coalesce(cur.decimal_places, 2)) END,
                        write_uid = %(uid)s, write_date = now() AT TIME ZONE 'UTC'
                      FROM stock_quant q2
                      LEFT JOIN capas c ON c.product_id = q2.product_id AND c.company_id = q2.company_id
                      LEFT JOIN res_currency cur ON cur.id = q2.moneda_reportes_id
                     WHERE q.id = q2.id AND q2.product_id = ANY(%(prod)s)
                """, {"prod": tramo, "uid": uid, "desde": desde})
                Quant.invalidate_model()
                if commit:
                    cr.commit()

        Producto = self.env["product.product"].with_user(self.inventory_user_id)
        if "ultimo_costo_mr" in Producto._fields:
            for n, tramo in enumerate(pasos, start=1):
                self._apl_etapa(_("Último costo de los productos (%d/%d)") % (n, len(pasos)), commit)
                registros = Producto.browse(tramo)
                self.env.add_to_compute(Producto._fields["ultimo_costo_mr"], registros)
                registros.flush_recordset(["ultimo_costo_mr"])
                plantillas = registros.product_tmpl_id
                if "ultimo_costo_mr" in plantillas._fields:
                    self.env.add_to_compute(plantillas._fields["ultimo_costo_mr"], plantillas)
                    plantillas.flush_recordset(["ultimo_costo_mr"])
                if commit:
                    cr.commit()

        Orderpoint = self.env["stock.warehouse.orderpoint"].with_user(self.inventory_user_id)
        for n, tramo in enumerate(pasos, start=1):
            self._apl_etapa(_("Puntos de reorden (%d/%d)") % (n, len(pasos)), commit)
            puntos = Orderpoint.with_context(active_test=False).search([("product_id", "in", tramo)])
            if puntos:
                self.env.add_to_compute(Orderpoint._fields["qty_to_order"], puntos)
                puntos.flush_recordset(["qty_to_order"])
            if commit:
                cr.commit()

    def _apl_etapa(self, texto, commit):
        """Muestra en el widget qué recálculo está corriendo."""
        if commit:
            self.write({"apply_step": texto})
            self.env.cr.commit()

    def _finalizar_aplicacion(self):
        self.ensure_one()
        t0 = time.time()
        self.env.cr.execute("SELECT DISTINCT product_id FROM {t} WHERE apply_via = 'sql'"
                            .format(t=self._staging_name()))
        productos = [r[0] for r in self.env.cr.fetchall()]
        self.env.cr.execute("SELECT count(DISTINCT product_id) FROM {t} WHERE apply_via = 'orm'"
                            .format(t=self._staging_name()))
        productos_orm = self.env.cr.fetchone()[0]
        try:
            self._apl_recalculos_finales(productos, self.apply_started_at)
        except Exception as e:
            self.env.cr.rollback()
            self.env.clear()
            self.write({"state": "error", "apply_ended_at": fields.Datetime.now(), "apply_step": False})
            self._log("ERROR en los recálculos finales: %s. Reanudar los vuelve a correr." % e)
            self.env.cr.commit()
            _logger.exception("[forum_partner_import] recálculos finales fallidos")
            return
        self.write({"state": "applied", "apply_ended_at": fields.Datetime.now(), "apply_step": False})
        self.env.registry.clear_cache()
        # Primera pasada de invariantes, sobre el 100% de lo aplicado.
        try:
            self._verificar_invariantes()
        except Exception as e:
            self.env.cr.rollback()
            self._log("La verificación por invariantes falló: %s" % e)
            _logger.exception("[forum_partner_import] verificación posterior al apply")
        self._log("Ajuste aplicado. Quants ajustados=%d Sin diferencia=%d Errores=%d | "
                  "vía ORM: %d celdas de %d productos | recálculos finales de %d productos en %.1fs."
                  % (self.applied_count, self.apply_no_diff, self.apply_errors,
                     self.apply_via_orm, productos_orm, len(productos), time.time() - t0))
        if self.apply_errors:
            self._log("Los quants con error conservan su conteo en Inventario físico y la "
                      "tabla staging %s tiene el motivo de cada uno." % self._staging_name())
        self.env.cr.commit()
