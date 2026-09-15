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
# `action_cancelar`.
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
    apply_step = fields.Char(string="Etapa de la aplicación", readonly=True, copy=False)
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
            "apply_via_orm": 0, "apply_step": False,
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

        No se escribe la fila del batch. La tanda en curso la escribe al
        terminar, y dos escrituras concurrentes sobre la misma fila hacen fallar
        su commit con SerializationFailure: se perdía la tanda entera y el batch
        quedaba en error en vez de cancelado. El pedido va a ir.config_parameter
        y lo lee la corrida siguiente del cron, que arranca con otra transacción.
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
        self._apl_preparar_staging()
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
        cuenta = {"aplicado": 0, "sin_diferencia": 0, "error": 0, "orm": 0, "segundos_orm": 0.0}
        if not filas:
            return cuenta
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
            self._apl_sql(t, filas_sql, resultado, tiempos)
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
            # costo distinto de cero, costo que no es FIFO, seguimiento por lote/serie
            """
            WITH p AS (SELECT DISTINCT product_id, company_id FROM forum_apl_f)
            SELECT p.product_id
              FROM p
              JOIN product_product pp ON pp.id = p.product_id
              JOIN product_template pt ON pt.id = pp.product_tmpl_id
              LEFT JOIN ir_property sp ON sp.name = 'standard_price' AND sp.company_id = p.company_id
                    AND sp.res_id = 'product.product,' || p.product_id
              LEFT JOIN ir_property spd ON spd.name = 'standard_price' AND spd.company_id = p.company_id
                    AND spd.res_id IS NULL
              LEFT JOIN ir_property cm ON cm.name = 'property_cost_method' AND cm.company_id = p.company_id
                    AND cm.res_id = 'product.category,' || pt.categ_id
              LEFT JOIN ir_property cmd ON cmd.name = 'property_cost_method' AND cmd.company_id = p.company_id
                    AND cmd.res_id IS NULL
             WHERE coalesce(sp.value_float, spd.value_float, 0) <> 0
                OR coalesce(cm.value_text, cmd.value_text, 'standard') <> 'fifo'
                OR pt.tracking <> 'none'
            """,
            # capas con valor, o negativas (vacuum)
            """
            SELECT DISTINCT l.product_id
              FROM stock_valuation_layer l
              JOIN (SELECT DISTINCT product_id, company_id FROM forum_apl_f) p
                ON p.product_id = l.product_id AND p.company_id = l.company_id
             WHERE l.value <> 0 OR l.remaining_value <> 0 OR l.remaining_qty < 0
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

    def _apl_sql(self, t, filas, resultado, tiempos=None):
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
                   0::numeric AS faltante
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
             WHERE s.row_num = ANY(%(filas)s)
        """.format(t=t, dec_rep=(
            '(SELECT decimal_places FROM res_currency WHERE id = c."monedaDeReporte")'
            if "monedaDeReporte" in self.env["res.company"]._fields else "NULL::int")),
            {"filas": filas, "lang": lang})

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
        explicitos_svl = {
            "id": "a.svl_id", "company_id": "a.company_id", "product_id": "a.product_id",
            "categ_id": "a.categ_id", "stock_move_id": "a.move_id",
            "description": "%(nombre_upd)s || ' - ' || a.prod_name",
            "quantity": capa("quantity", "a.diff"),
            "unit_cost": capa("unit_cost", "0"),
            "value": capa("value", "0"),
            "remaining_qty": capa("remaining_qty", "CASE WHEN a.diff > 0 THEN a.diff ELSE -a.faltante END"),
            "remaining_value": "CASE WHEN a.diff > 0 THEN %s ELSE NULL END" % capa("remaining_value", "0"),
            "create_uid": "%(uid)s", "write_uid": "%(uid)s",
            "create_date": "now() AT TIME ZONE 'UTC'", "write_date": "now() AT TIME ZONE 'UTC'",
        }
        if "moneda_reporte_id" in Layer._fields:
            explicitos_svl["moneda_reporte_id"] = 'c."monedaDeReporte"'
            for campo in SVL_TCHISTORICO_CERO:
                if campo in Layer._fields:
                    # tchistorico crea la capa en 0 con moneda_reporte_id=False en
                    # los valores: los Monetary se guardan sin moneda que redondee.
                    explicitos_svl[campo] = capa(campo, "0", None)
        cols_d, vals_d, params_d = self._apl_defaults("stock.valuation.layer", explicitos_svl)
        params.update(params_d)
        cr.execute("""
            INSERT INTO stock_valuation_layer ({cols})
            SELECT {vals}
              FROM forum_apl a JOIN res_company c ON c.id = a.company_id
             WHERE NOT a.es_cero
             ORDER BY a.svl_id
        """.format(cols=", ".join(['"%s"' % c for c in explicitos_svl] + cols_d),
                   vals=", ".join(list(explicitos_svl.values()) + vals_d)), params)
        consumo = self._apl_num("stock.valuation.layer", "remaining_qty",
                                "l.remaining_qty - least(c.remaining_qty, s.consumir - c.antes)")

        tiempos("SQL: capas")
        #    Consumo FIFO de las salidas (_run_fifo): capas con saldo en orden
        #    create_date, id; las entradas de la tanda entran al final.
        cr.execute("""
            WITH salidas AS (
                SELECT product_id, company_id, sum(-diff) - sum(faltante) AS consumir
                  FROM forum_apl WHERE diff < 0 AND NOT es_cero GROUP BY 1, 2
            ),
            candidatas AS (
                SELECT l.id, l.product_id, l.company_id, l.remaining_qty,
                       coalesce(sum(l.remaining_qty) OVER (
                           PARTITION BY l.product_id, l.company_id ORDER BY l.create_date, l.id
                           ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS antes
                  FROM stock_valuation_layer l
                  JOIN salidas s ON s.product_id = l.product_id AND s.company_id = l.company_id
                 WHERE l.remaining_qty > 0
            )
            UPDATE stock_valuation_layer l
               SET remaining_qty = {consumo},
                   write_uid = %(uid)s, write_date = now() AT TIME ZONE 'UTC'
              FROM candidatas c
              JOIN salidas s ON s.product_id = c.product_id AND s.company_id = c.company_id
             WHERE l.id = c.id AND s.consumir > c.antes
        """.replace("{consumo}", consumo), params)

        tiempos("SQL: consumo FIFO")
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
        self._log("Ajuste aplicado. Quants ajustados=%d Sin diferencia=%d Errores=%d | "
                  "vía ORM: %d celdas de %d productos | recálculos finales de %d productos en %.1fs."
                  % (self.applied_count, self.apply_no_diff, self.apply_errors,
                     self.apply_via_orm, productos_orm, len(productos), time.time() - t0))
        if self.apply_errors:
            self._log("Los quants con error conservan su conteo en Inventario físico y la "
                      "tabla staging %s tiene el motivo de cada uno." % self._staging_name())
        self.env.cr.commit()
