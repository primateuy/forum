# -*- coding: utf-8 -*-
"""Ajuste de inventario multi-sucursal desde un xlsx de doble entrada.

El archivo es una tabla: una fila por variante, una columna por sucursal, y en
el cruce la cantidad contada. Se "des-pivotea" al cargar: cada celda con valor
pasa a ser una fila de staging (producto, ubicación, cantidad).

Dos fases, cada una con su puntero, su cron y su avance en pantalla:

1. **Carga** (`processing`). Upsert de `stock.quant` por SQL, por tandas: deja
   cada quant con `inventory_quantity` = contado e `inventory_quantity_set`,
   igual que si alguien lo hubiera tipeado en *Inventario físico*. No mueve
   stock ni contabilidad: se puede revisar y repetir.
2. **Aplicación** (`applying`). Por el ORM (`_apply_inventory`), también por
   tandas. Es la que crea los movimientos, la valuación y los asientos; por eso
   no se hace por SQL.

Todo lo que es exclusivo de este tipo vive acá. El modelo base despacha a estos
métodos mirando `import_type`, y para clientes cae siempre a `super()`.
"""
import csv
import logging
import os
import tempfile
from datetime import datetime

from psycopg2.extras import execute_values

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import openpyxl
except ImportError:  # declarado en external_dependencies del manifest
    openpyxl = None

NOMBRE_XLSX = "ajuste_inventario_20260912.xlsx"
RUTA_XLSX = "forum_partner_import/data/" + NOMBRE_XLSX
FECHA_CONTEO = "12/09/2026"

# Estructura de la tabla de doble entrada (1-based, como la ve Excel).
FILA_ALMACENES = 1
FILA_UBICACIONES = 2
FILA_CABECERA = 3
PRIMERA_FILA_DATOS = 4
# Columnas de producto (A..E). Solo `id` se usa para resolver.
COLUMNAS_PRODUCTO = ("id", "default_code", "name")
PRIMERA_COLUMNA_UBICACION = 6   # F

# Acciones del staging que llegan a tocar un quant.
ACCIONES_QUANT = ("crear", "actualizar", "en_cero")


class ForumImportBatchInventario(models.Model):
    _inherit = "forum.import.batch"

    import_type = fields.Selection(
        selection_add=[("inventario", "Ajuste de inventario")],
        ondelete={"inventario": "set default"},
    )

    # ------------------------------------------------------------------
    # Configuración del ajuste
    # ------------------------------------------------------------------
    inventory_user_id = fields.Many2one(
        "res.users", string="Responsable del conteo", ondelete="restrict",
        default=lambda self: self.env.user,
        help="Queda como responsable de cada quant contado y es el usuario con "
             "el que se aplica el ajuste: tiene que ser administrador de inventario.",
    )
    inventory_reason = fields.Char(
        string="Motivo del ajuste",
        help="Se guarda en el motivo del quant y viaja al origen de cada "
             "movimiento. Si se deja vacío, se completa al cargar con "
             "'Ajuste inventario FORUM <fecha del conteo> - batch <id>'.",
    )

    # ------------------------------------------------------------------
    # Contadores de la carga
    # ------------------------------------------------------------------
    quants_created = fields.Integer(string="Quants creados", readonly=True, copy=False)
    quants_updated = fields.Integer(string="Quants actualizados", readonly=True, copy=False)
    quants_zero = fields.Integer(
        string="En cero sin quant", readonly=True, copy=False,
        help="Celdas con 0 para un producto que no tiene quant en esa ubicación: "
             "ya está en cero, no hace falta crear nada.",
    )

    @api.onchange("import_type")
    def _onchange_import_type_nombre(self):
        """Ajusta el nombre sugerido mientras siga siendo uno de los por defecto."""
        por_defecto = {
            "clientes": _("Importación de clientes FORUM"),
            "inventario": _("Ajuste de inventario FORUM %s") % FECHA_CONTEO,
        }
        if not self.name or self.name in por_defecto.values() \
                or self.name == "Importación de clientes FORUM":
            self.name = por_defecto.get(self.import_type, self.name)

    # ==================================================================
    # Despacho desde el modelo base
    # ==================================================================
    def _es_inventario(self):
        self.ensure_one()
        return self.import_type == "inventario"

    def _ruta_relativa_archivo(self):
        if self._es_inventario():
            return RUTA_XLSX
        return super()._ruta_relativa_archivo()

    def _validar_configuracion(self):
        if not self._es_inventario():
            return super()._validar_configuracion()
        if openpyxl is None:
            raise UserError(_("Falta la librería de Python openpyxl en el servidor."))
        if not self.inventory_user_id:
            raise UserError(_("Falta completar el responsable del conteo."))
        if not self.inventory_user_id.has_group("stock.group_stock_manager"):
            raise UserError(_("%s no es administrador de inventario: no va a poder "
                              "aplicar el ajuste.") % self.inventory_user_id.display_name)

    def _valores_reset_carga(self):
        valores = super()._valores_reset_carga()
        valores.update({"quants_created": 0, "quants_updated": 0, "quants_zero": 0})
        return valores

    def _antes_de_iniciar(self):
        # El backup de tarjetas es de clientes. Acá no se toca stock en la
        # carga (solo el conteo), y el camino de vuelta real es el dump.
        if not self._es_inventario():
            return super()._antes_de_iniciar()

    def _pasos_de_carga(self):
        if not self._es_inventario():
            return super()._pasos_de_carga()
        return [
            (_("Creando la tabla de trabajo"),          self._inv_crear_staging),
            (_("Leyendo el archivo"),                   self._inv_leer_xlsx),
        ] + self._inv_pasos_post_origen()

    def _inv_pasos_post_origen(self):
        """Lo que va DESPUÉS de leer el origen, sea cual sea el origen.

        Está separado a propósito: el archivo no es la única forma de armar un
        conteo. `cargar_celdas_externas` usa exactamente estos pasos, así que
        un conteo que viene de otro sistema pasa por las mismas validaciones,
        el mismo filtrado y la misma decisión de acción por celda que uno que
        viene de un Excel. Si estos pasos cambian, cambian para los dos.
        """
        return [
            (_("Resolviendo ubicaciones"),              self._inv_resolver_ubicaciones),
            (_("Resolviendo productos"),                self._inv_resolver_productos),
            (_("Filtrando almacenables y con lote"),    self._inv_filtrar_productos),
            (_("Buscando quants existentes"),           self._inv_quants_existentes),
            (_("Definiendo la acción de cada celda"),   self._inv_accion_efectiva),
            (_("Calculando estadísticas"),              self._pp_analyze),
        ]

    # ------------------------------------------------------------------
    # Costura pública: un conteo armado por otro módulo
    # ------------------------------------------------------------------
    def cargar_celdas_externas(self, filas, origen=""):
        """Arma el staging con celdas que preparó OTRO módulo. Contrato público.

        Pensado para orígenes que no son un archivo —hoy, la conciliación de
        stock contra WIS, que arma el conteo consultando el WMS—. El que llama
        no necesita conocer la tabla de trabajo ni sus columnas: entrega las
        celdas y el motor hace el resto, con las mismas validaciones que el
        camino del Excel.

        🔴 **Se llama, no se hereda.** Heredar `forum.import.batch` obligaría al
        otro módulo a depender de éste, y el que tiene que usarlo es un módulo
        COMPARTIDO entre clientes: no puede depender de un módulo de Forum.
        Llamarlo sólo pide que el modelo exista::

            Batch = self.env.get("forum.import.batch")
            if Batch is not None:
                batch.cargar_celdas_externas(filas, origen="WIS")

        `filas`: iterable de dicts con

            product_id   (int, obligatorio)  la variante a ajustar
            location_id  (int, obligatorio)  la ubicación del conteo
            cantidad     (float, obligatorio) lo contado, NUNCA la diferencia

        🔴 `cantidad` es **el stock que debe quedar**, no el delta: es lo mismo
        que dice una celda del Excel. Pasar la diferencia haría un ajuste que
        parece correcto y deja el stock en cualquier lado.

        Deja el batch en `ready`, listo para «Aplicar ajuste». No publica ni
        aplica nada: esa sigue siendo una decisión de una persona.

        Corre sincrónico y no por el cron, a diferencia del Excel: acá las
        filas ya vienen armadas y lo que queda son consultas SQL sobre la tabla
        de trabajo. Leer 918.061 celdas de un xlsx tarda minutos; esto no.
        """
        self.ensure_one()
        if not self._es_inventario():
            raise UserError(_("Este batch no es de ajuste de inventario."))
        if self.state in ("applying", "posting", "reconciling"):
            raise UserError(_("El batch está en proceso: no se puede recargar el conteo."))
        # El responsable sí se valida —sin él el ajuste no se puede aplicar—,
        # pero no `_validar_configuracion` entera: exige openpyxl, y acá no hay
        # ningún archivo que leer.
        if not self.inventory_user_id:
            raise UserError(_("Falta completar el responsable del conteo."))
        if not self.inventory_user_id.has_group("stock.group_stock_manager"):
            raise UserError(_("%s no es administrador de inventario: no va a poder "
                              "aplicar el ajuste.") % self.inventory_user_id.display_name)

        filas = list(filas)
        if not filas:
            raise UserError(_("No hay celdas para cargar."))

        faltantes = [c for c in ("product_id", "location_id", "cantidad")
                     if any(f.get(c) is None for f in filas)]
        if faltantes:
            raise UserError(_("Faltan datos en las celdas recibidas: %s.")
                            % ", ".join(sorted(set(faltantes))))

        self.write(dict(self._valores_reset_carga(), state="loading",
                        loading_step=0, loading_steps_total=len(self._inv_pasos_post_origen()) + 1,
                        loading_phase=_("Armando el conteo"),
                        loading_started_at=fields.Datetime.now()))

        self._inv_crear_staging()
        self._inv_insertar_celdas_externas(filas)
        self._log("Conteo recibido de %s: %d celdas." % (origen or _("otro módulo"), len(filas)))

        for i, (etiqueta, metodo) in enumerate(self._inv_pasos_post_origen(), start=2):
            self.write({"loading_step": i - 1, "loading_phase": etiqueta})
            metodo()

        self.env.cr.execute("SELECT count(*) FROM %s" % self._staging_name())
        total = self.env.cr.fetchone()[0]
        self.write({"state": "ready", "total_rows": total,
                    "loading_step": len(self._inv_pasos_post_origen()) + 1,
                    "loading_phase": _("Listo")})
        self._log("Staging armado desde %s. %s"
                  % (origen or _("otro módulo"), self._resumen_staging()))
        return True

    def _inv_insertar_celdas_externas(self, filas):
        """Vuelca las celdas recibidas en la tabla de trabajo.

        La ubicación se escribe por NOMBRE, igual que la trae el Excel, para
        que `_inv_resolver_ubicaciones` la valide como a cualquier otra: que
        exista, que sea interna, que no esté repetida y que tenga compañía. El
        `location_id` que nos pasaron no se usa como atajo — si no resuelve,
        que falle acá y no al aplicar.
        """
        self.ensure_one()
        ubicaciones = self.env["stock.location"].browse(
            list({f["location_id"] for f in filas})).exists()
        nombres = {u.id: u.complete_name for u in ubicaciones}
        productos = self.env["product.product"].browse(
            list({f["product_id"] for f in filas})).exists()
        codigos = {p.id: (p.default_code or "", p.display_name or "") for p in productos}

        valores = []
        for n, fila in enumerate(filas, start=1):
            codigo, nombre = codigos.get(fila["product_id"], ("", ""))
            valores.append((
                n,                                    # fila_excel: para el dedup
                1,                                    # col_excel
                codigo,                               # default_code (informativo)
                nombre,                               # producto (informativo)
                nombres.get(fila["location_id"], ""), # ubicacion, por nombre
                str(fila["cantidad"]),                # cantidad_raw
                fila["cantidad"],                     # cantidad
                fila["product_id"],                   # ya resuelto
            ))
        execute_values(self.env.cr, """
            INSERT INTO {t} (fila_excel, col_excel, default_code, producto,
                             ubicacion, cantidad_raw, cantidad, product_id)
            VALUES %s
        """.format(t=self._staging_name()), valores, page_size=5000)

    def _procesar_tanda(self):
        if not self._es_inventario():
            return super()._procesar_tanda()
        return self._inv_procesar_tanda()

    def _resumen_staging(self):
        if not self._es_inventario():
            return super()._resumen_staging()
        t = self._staging_name()
        cr = self.env.cr
        cr.execute("SELECT accion_efectiva, count(*) FROM %s GROUP BY 1 ORDER BY 1" % t)
        reparto = ", ".join("%s=%s" % (a, n) for a, n in cr.fetchall())
        cr.execute("""
            SELECT coalesce(motivo, error), count(*) FROM {t}
             WHERE accion_efectiva IN ('ignorar', 'error')
             GROUP BY 1 ORDER BY 2 DESC
        """.format(t=t))
        motivos = "; ".join("%s: %s" % (m, n) for m, n in cr.fetchall()) or "-"
        cr.execute("""
            SELECT count(DISTINCT fila_excel), count(DISTINCT location_id),
                   count(DISTINCT company_id)
              FROM {t}
        """.format(t=t))
        filas, ubicaciones, companias = cr.fetchone()
        return (u"Celdas con valor: acciones efectivas %s. Filas de producto: %d. "
                u"Ubicaciones: %d (%d compañía/s). Ignoradas y errores por motivo: %s."
                % (reparto, filas, ubicaciones, companias, motivos))

    def _finalizar(self):
        if not self._es_inventario():
            return super()._finalizar()
        self.ensure_one()
        self.write({"state": "done", "ended_at": fields.Datetime.now()})
        self._log("Carga terminada. Quants creados=%d actualizados=%d en cero sin quant=%d "
                  "Ignoradas=%d Errores=%d. Falta aplicar el ajuste."
                  % (self.quants_created, self.quants_updated, self.quants_zero,
                     self.ignored, self.errors))
        self.env.cr.commit()

    def action_exportar_errores(self):
        """Para inventario exporta errores E ignoradas, cada una con su motivo."""
        if not self._es_inventario():
            return super().action_exportar_errores()
        self.ensure_one()
        if not self._staging_existe():
            raise UserError(_("Ya no existe la tabla staging de este batch."))
        carpeta = (self.backup_dir or "/tmp").strip()
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta = os.path.join(carpeta, "forum_ajuste_errores_%d_%s.csv" % (self.id, sello))
        with open(ruta, "wb") as fh:
            self.env.cr.copy_expert("""
                COPY (SELECT fila_excel, col_excel, xid, default_code, producto,
                             almacen, ubicacion, cantidad_raw, accion_efectiva,
                             motivo, error, {extra}
                        FROM {t}
                       WHERE accion_efectiva IN ('error', 'ignorar') {cond}
                       ORDER BY fila_excel, col_excel)
                TO STDOUT WITH (FORMAT csv, HEADER true)
            """.format(t=self._staging_name(), **self._inv_columnas_export()), fh)
        self._log("Errores e ignoradas exportados a %s" % ruta)
        return self._notificar(_("Errores exportados"), ruta)

    def _inv_columnas_export(self):
        """Columnas extra del export de errores (la aplicación agrega las suyas)."""
        return {"extra": "NULL AS resultado_aplicacion", "cond": ""}

    # ==================================================================
    # Carga del staging
    # ==================================================================
    def _inv_crear_staging(self):
        """Tabla UNLOGGED, una fila por celda con valor."""
        t = self._staging_name()
        cr = self.env.cr
        cr.execute("DROP TABLE IF EXISTS %s" % t)
        cr.execute("""
            CREATE UNLOGGED TABLE {t} (
                row_num          bigserial PRIMARY KEY,
                -- lo que trae el archivo
                fila_excel       integer,
                col_excel        integer,
                xid              varchar,
                default_code     varchar,
                producto         varchar,
                almacen          varchar,
                ubicacion        varchar,
                cantidad_raw     varchar,
                -- derivados del pre-procesamiento
                cantidad         numeric,
                product_id       integer,
                location_id      integer,
                company_id       integer,
                quant_id         integer,
                accion_efectiva  varchar,
                motivo           varchar,
                error            text,
                -- carga de quants
                resultado_carga  varchar,
                procesado        boolean DEFAULT false,
                -- aplicación del ajuste
                apply_seq        integer,
                apply_resultado  varchar,
                apply_error      text
            )
        """.format(t=t))
        cr.execute("CREATE INDEX {t}_pend_idx ON {t} (row_num) WHERE procesado = false".format(t=t))
        cr.execute("CREATE INDEX {t}_xid_idx ON {t} (xid)".format(t=t))
        if not self.inventory_reason:
            self.inventory_reason = "Ajuste inventario FORUM %s - batch %d" % (FECHA_CONTEO, self.id)
        self._log("Tabla staging %s creada." % t)

    def _inv_leer_xlsx(self):
        """Lee el xlsx en streaming y lo vuelca des-pivoteado con COPY.

        `read_only=True` hace que openpyxl no arme el árbol de toda la hoja: va
        fila por fila. Cada celda con valor se escribe a un CSV temporal, que
        entra de una sola vez con COPY. Una celda vacía no genera fila; un 0 sí.
        """
        self.ensure_one()
        ruta = self._ruta_absoluta_archivo()
        libro = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
        try:
            hoja = libro.worksheets[0]
            ubicaciones, almacenes = {}, {}
            celdas, sin_encabezado = 0, set()
            with tempfile.TemporaryFile("w+", newline="", encoding="utf-8") as tmp:
                escritor = csv.writer(tmp)
                for n_fila, fila in enumerate(hoja.iter_rows(values_only=True), start=1):
                    if n_fila == FILA_ALMACENES:
                        almacenes = self._inv_mapa_columnas(fila)
                        continue
                    if n_fila == FILA_UBICACIONES:
                        ubicaciones = self._inv_mapa_columnas(fila)
                        continue
                    if n_fila == FILA_CABECERA:
                        self._inv_validar_cabecera(fila, ubicaciones)
                        continue
                    xid = fila[0] if fila else None
                    if xid is None or not str(xid).strip():
                        if any(v not in (None, "") for v in fila):
                            _logger.warning("[forum_partner_import] fila %d sin id con datos", n_fila)
                        continue
                    xid = str(xid).strip()
                    codigo = fila[1] if len(fila) > 1 else None
                    nombre = fila[2] if len(fila) > 2 else None
                    for n_col in range(PRIMERA_COLUMNA_UBICACION, len(fila) + 1):
                        valor = fila[n_col - 1]
                        if valor is None or (isinstance(valor, str) and not valor.strip()):
                            continue
                        if n_col not in ubicaciones:
                            sin_encabezado.add(n_col)
                            continue
                        escritor.writerow((
                            n_fila, n_col, xid, codigo, nombre,
                            almacenes.get(n_col), ubicaciones[n_col],
                            repr(valor) if isinstance(valor, float) else str(valor).strip(),
                        ))
                        celdas += 1
                if sin_encabezado:
                    raise UserError(_(
                        "Hay cantidades en columnas sin ubicación en la fila %(fila)d: %(cols)s. "
                        "No se carga nada.",
                        fila=FILA_UBICACIONES,
                        cols=", ".join(openpyxl.utils.get_column_letter(c) for c in sorted(sin_encabezado))))
                tmp.seek(0)
                self.env.cr.copy_expert("""
                    COPY {t} (fila_excel, col_excel, xid, default_code, producto,
                              almacen, ubicacion, cantidad_raw)
                    FROM STDIN WITH (FORMAT csv)
                """.format(t=self._staging_name()), tmp)
        finally:
            libro.close()

        self.env.cr.execute("""
            UPDATE {t} SET cantidad = CASE
                WHEN cantidad_raw ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN cantidad_raw::numeric END
        """.format(t=self._staging_name()))
        self._log("Archivo leído: %d celdas con valor en %d ubicaciones." % (celdas, len(ubicaciones)))

    @staticmethod
    def _inv_mapa_columnas(fila):
        """{número de columna: texto} de las columnas de ubicación con valor."""
        mapa = {}
        for n_col in range(PRIMERA_COLUMNA_UBICACION, len(fila) + 1):
            valor = fila[n_col - 1]
            if valor is not None and str(valor).strip():
                mapa[n_col] = str(valor).strip()
        return mapa

    def _inv_validar_cabecera(self, fila, ubicaciones):
        """Estructura mínima: 'id' en A3 y ubicaciones únicas en la fila 2."""
        if not fila or str(fila[0] or "").strip().lower() != "id":
            raise UserError(_(
                "La celda A%(fila)d tiene que decir 'id' (ID externo de la variante). "
                "¿Cambió el formato del archivo?", fila=FILA_CABECERA))
        if not ubicaciones:
            raise UserError(_("La fila %d no tiene ninguna ubicación.") % FILA_UBICACIONES)
        vistas, repetidas = set(), set()
        for nombre in ubicaciones.values():
            (repetidas if nombre in vistas else vistas).add(nombre)
        if repetidas:
            raise UserError(_("Ubicaciones repetidas en la fila %(fila)d: %(nombres)s.",
                              fila=FILA_UBICACIONES, nombres=", ".join(sorted(repetidas))))

    # ==================================================================
    # Pre-procesamiento (set-based)
    # ==================================================================
    def _inv_resolver_ubicaciones(self):
        """Fila 2 → stock.location por complete_name exacto. Bloqueante.

        Cada celda toma la compañía DE SU UBICACIÓN, nunca la del usuario: el
        quant la necesita igual a la de la ubicación (es un related stored).
        """
        t = self._staging_name()
        cr = self.env.cr
        cr.execute("""
            WITH nombres AS (SELECT DISTINCT ubicacion FROM {t}),
            candidatas AS (
                SELECT n.ubicacion, l.id, l.usage, l.company_id,
                       count(l.id) OVER (PARTITION BY n.ubicacion) AS n_match
                  FROM nombres n
                  LEFT JOIN stock_location l
                         ON l.complete_name = n.ubicacion AND l.active
            )
            SELECT ubicacion,
                   CASE WHEN id IS NULL THEN 'no existe (o está archivada)'
                        WHEN n_match > 1 THEN 'hay ' || n_match || ' ubicaciones con ese nombre'
                        WHEN usage <> 'internal' THEN 'no es una ubicación interna (' || usage || ')'
                        WHEN company_id IS NULL THEN 'no tiene compañía'
                   END
              FROM candidatas
             WHERE id IS NULL OR n_match > 1 OR usage <> 'internal' OR company_id IS NULL
             ORDER BY 1
        """.format(t=t))
        problemas = cr.fetchall()
        if problemas:
            raise UserError(_("No se carga nada: %(n)d ubicación/es de la fila %(fila)d no "
                              "resuelven. %(detalle)s",
                              n=len(problemas), fila=FILA_UBICACIONES,
                              detalle="; ".join("'%s' %s" % p for p in problemas)))
        cr.execute("""
            UPDATE {t} s SET location_id = l.id, company_id = l.company_id
              FROM stock_location l
             WHERE l.complete_name = s.ubicacion AND l.active
        """.format(t=t))
        cr.execute("""
            SELECT c.name, count(DISTINCT s.location_id)
              FROM {t} s JOIN res_company c ON c.id = s.company_id
             GROUP BY 1 ORDER BY 2 DESC
        """.format(t=t))
        self._log("Ubicaciones resueltas por compañía: %s"
                  % ", ".join("%s=%d" % fila for fila in cr.fetchall()))

    def _inv_resolver_productos(self):
        """ID externo → product.product vía ir_model_data (fuente de verdad).

        No se parsea el número embebido en `__export__.product_product_<n>_…`:
        el id externo puede apuntar a otro registro que el que sugiere el nombre.
        """
        t = self._staging_name()
        cr = self.env.cr
        cr.execute("""
            UPDATE {t} s SET product_id = d.res_id
              FROM ir_model_data d
             WHERE d.model = 'product.product'
               AND d.module = split_part(s.xid, '.', 1)
               AND d.name = substring(s.xid FROM position('.' IN s.xid) + 1)
        """.format(t=t))
        cr.execute("""
            UPDATE {t} s SET error = CASE
                    WHEN position('.' IN s.xid) = 0 THEN 'ID externo sin módulo'
                    WHEN EXISTS (SELECT 1 FROM ir_model_data d
                                  WHERE d.module = split_part(s.xid, '.', 1)
                                    AND d.name = substring(s.xid FROM position('.' IN s.xid) + 1))
                        THEN 'El ID externo no es de una variante de producto'
                    ELSE 'ID externo no encontrado en la base'
                END
             WHERE s.product_id IS NULL
        """.format(t=t))
        # La variante pudo haberse borrado dejando el ir_model_data huérfano.
        cr.execute("""
            UPDATE {t} s SET error = 'El ID externo apunta a un producto que ya no existe',
                             product_id = NULL
             WHERE s.product_id IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM product_product p WHERE p.id = s.product_id)
        """.format(t=t))
        # Cantidades inválidas.
        cr.execute("""
            UPDATE {t} SET error = coalesce(error || ' | ', '') ||
                   CASE WHEN cantidad IS NULL THEN 'Cantidad no numérica: ' || cantidad_raw
                        ELSE 'Cantidad negativa' END
             WHERE cantidad IS NULL OR cantidad < 0
        """.format(t=t))
        # Mismo par (producto, ubicación) dos veces: por un ID externo repetido
        # o por dos IDs externos del mismo producto. Gana la primera fila.
        cr.execute("""
            WITH rep AS (
                SELECT row_num,
                       min(fila_excel) OVER (PARTITION BY product_id, location_id) AS primera
                  FROM {t} WHERE product_id IS NOT NULL
            )
            UPDATE {t} s SET error = coalesce(s.error || ' | ', '') ||
                   'Producto repetido en el archivo (ya está en la fila ' || r.primera || ')'
              FROM rep r
             WHERE r.row_num = s.row_num AND s.fila_excel > r.primera
        """.format(t=t))

    def _inv_filtrar_productos(self):
        """No almacenables y con lote/serie se ignoran, con motivo. No son error."""
        t = self._staging_name()
        cr = self.env.cr
        cr.execute("""
            UPDATE {t} s SET motivo = CASE
                    WHEN pt.type <> 'product' THEN
                        'No almacenable (' || CASE pt.type WHEN 'consu' THEN 'consumible'
                                                           WHEN 'service' THEN 'servicio'
                                                           ELSE pt.type END || ')'
                    WHEN pt.tracking IN ('lot', 'serial') THEN
                        'Seguimiento por ' || CASE pt.tracking WHEN 'lot' THEN 'lote' ELSE 'número de serie' END
                        || ': no se ajusta un quant sin lote'
                END
              FROM product_product pp
              JOIN product_template pt ON pt.id = pp.product_tmpl_id
             WHERE pp.id = s.product_id
               AND s.error IS NULL
               AND (pt.type <> 'product' OR pt.tracking IN ('lot', 'serial'))
        """.format(t=t))
        # Un producto restringido a otra compañía no puede tener stock en esta.
        cr.execute("""
            UPDATE {t} s SET error = 'El producto es de otra compañía que la ubicación'
              FROM product_product pp
              JOIN product_template pt ON pt.id = pp.product_tmpl_id
             WHERE pp.id = s.product_id AND s.error IS NULL AND s.motivo IS NULL
               AND pt.company_id IS NOT NULL AND pt.company_id <> s.company_id
        """.format(t=t))

    def _inv_quants_existentes(self):
        """Quant sin lote, paquete ni propietario de cada par, si existe.

        stock_quant no tiene constraint de unicidad: si hubiera más de uno para
        el par, ajustar uno solo dejaría el total distinto del contado. Se marca
        como error en vez de elegir uno.
        """
        t = self._staging_name()
        cr = self.env.cr
        cr.execute("""
            WITH q AS (
                SELECT q.product_id, q.location_id, min(q.id) AS id, count(*) AS n,
                       string_agg(q.id::text, ',' ORDER BY q.id) AS ids
                  FROM stock_quant q
                 WHERE q.lot_id IS NULL AND q.package_id IS NULL AND q.owner_id IS NULL
                   AND q.location_id IN (SELECT DISTINCT location_id FROM {t})
                 GROUP BY 1, 2
            )
            UPDATE {t} s SET
                quant_id = CASE WHEN q.n = 1 THEN q.id END,
                error = CASE WHEN q.n > 1 THEN
                    'Hay ' || q.n || ' quants para el producto en la ubicación (ids ' || q.ids || ')'
                END
              FROM q
             WHERE q.product_id = s.product_id AND q.location_id = s.location_id
               AND s.error IS NULL
        """.format(t=t))

    def _inv_accion_efectiva(self):
        """Qué se hace con cada celda.

        - error:      no se toca nada (ver `error`)
        - ignorar:    no almacenable o con lote (ver `motivo`)
        - actualizar: ya hay quant, se le pone el contado
        - crear:      no hay quant y el contado no es 0: se crea con stock 0
        - en_cero:    no hay quant y el contado es 0: ya está en cero

        Ojo con la semántica del 0, que es la opuesta a la de clientes: acá un 0
        es un dato ("en esta sucursal no hay") y sí genera línea.
        """
        t = self._staging_name()
        self.env.cr.execute("""
            UPDATE {t} SET accion_efectiva = CASE
                WHEN error IS NOT NULL     THEN 'error'
                WHEN motivo IS NOT NULL    THEN 'ignorar'
                WHEN quant_id IS NOT NULL  THEN 'actualizar'
                WHEN cantidad = 0          THEN 'en_cero'
                ELSE                            'crear'
            END
        """.format(t=t))

    # ==================================================================
    # Carga de quants por tandas (SQL)
    # ==================================================================
    def _inv_campos_extra_quant(self):
        """Columnas stored de stock.quant que agregan otros módulos instalados.

        El INSERT cubre explícitamente los campos del core. Para lo que agregue
        cualquier otro módulo se mira el modelo real:

        - related stored que cuelgan de `company_id` o `location_id` (ej. la
          moneda de reportes de tchistorico) → se resuelven con un join;
        - calculados stored numéricos (ej. el valor de reporte) → 0, que es lo
          que da el compute para un quant sin stock; se recalculan solos cuando
          el apply crea la valuación;
        - `reason` de stock_change_qty_reason → el motivo del ajuste.

        Devuelve [(columna, expresión SQL)]. Lo que no encaja en ningún caso se
        registra en el log, para que no quede un NULL silencioso.
        """
        Quant = self.env["stock.quant"]
        nucleo = {
            "id", "product_id", "location_id", "company_id", "storage_category_id",
            "lot_id", "package_id", "owner_id", "quantity", "reserved_quantity",
            "inventory_quantity", "inventory_diff_quantity", "inventory_quantity_set",
            "inventory_date", "user_id", "in_date", "create_uid", "create_date",
            "write_uid", "write_date", "accounting_date", "preset_reason_id",
        }
        extra, sin_valor = [], []
        for nombre, campo in Quant._fields.items():
            if nombre in nucleo or not campo.store or not campo.column_type:
                continue
            if nombre == "reason":
                extra.append((nombre, "%(reason)s"))
            elif campo.related and len(campo.related.split(".")) == 2 \
                    and campo.related.split(".")[0] in ("company_id", "location_id"):
                origen, destino = campo.related.split(".")
                tabla = "c" if origen == "company_id" else "l"
                extra.append((nombre, '%s."%s"' % (tabla, destino)))
            elif campo.compute and campo.type in ("float", "monetary", "integer"):
                extra.append((nombre, "0"))
            elif not campo.required:
                sin_valor.append(nombre)
        if sin_valor:
            _logger.info("[forum_partner_import] stock.quant: sin valor explícito en el INSERT: %s",
                         ", ".join(sin_valor))
        return extra

    def _inv_procesar_tanda(self):
        """Upsert de quants de una tanda de celdas.

        La tabla stock_quant se bloquea en modo SHARE ROW EXCLUSIVE mientras dura
        la tanda (décimas de segundo): nadie más puede crear ni modificar quants
        en ese lapso. Sin esto, una venta del POS podría crear el quant del mismo
        par entre el "¿existe?" y el INSERT, y el par quedaría partido en dos
        quants: el ajuste corregiría uno solo y el total no daría el contado.

        Es idempotente: correrla dos veces deja lo mismo. El quant se busca otra
        vez al momento de la tanda (pudo aparecer desde el pre-proceso), se
        actualiza si existe y se inserta si no.
        """
        self.ensure_one()
        desde = self.offset + 1
        hasta = self.offset + self.batch_size
        t = self._staging_name()
        cr = self.env.cr
        params = {
            "desde": desde, "hasta": hasta, "acciones": list(ACCIONES_QUANT),
            "hoy": fields.Date.context_today(self),
            "usuario": self.inventory_user_id.id, "uid": self.env.uid,
            "reason": self.inventory_reason,
        }

        cr.execute("LOCK TABLE stock_quant IN SHARE ROW EXCLUSIVE MODE")

        # 1. Quant vigente de cada par, ahora que la tabla está bloqueada. Lo que
        #    vio el pre-proceso ya no vale: el quant pudo aparecer o desaparecer.
        cr.execute("""
            UPDATE {t} SET quant_id = NULL,
                   accion_efectiva = CASE WHEN cantidad = 0 THEN 'en_cero' ELSE 'crear' END
             WHERE row_num BETWEEN %(desde)s AND %(hasta)s
               AND accion_efectiva = ANY(%(acciones)s)
        """.format(t=t), params)
        cr.execute("""
            WITH q AS (
                SELECT q.product_id, q.location_id, min(q.id) AS id, count(*) AS n,
                       string_agg(q.id::text, ',' ORDER BY q.id) AS ids
                  FROM stock_quant q
                  JOIN {t} s ON s.product_id = q.product_id AND s.location_id = q.location_id
                 WHERE s.row_num BETWEEN %(desde)s AND %(hasta)s
                   AND s.accion_efectiva = ANY(%(acciones)s)
                   AND q.lot_id IS NULL AND q.package_id IS NULL AND q.owner_id IS NULL
                 GROUP BY 1, 2
            )
            UPDATE {t} s SET
                quant_id = CASE WHEN q.n = 1 THEN q.id END,
                accion_efectiva = CASE WHEN q.n = 1 THEN 'actualizar' ELSE 'error' END,
                error = CASE WHEN q.n > 1 THEN
                    'Hay ' || q.n || ' quants para el producto en la ubicación (ids ' || q.ids || ')'
                END
              FROM q
             WHERE q.product_id = s.product_id AND q.location_id = s.location_id
               AND s.row_num BETWEEN %(desde)s AND %(hasta)s
               AND s.accion_efectiva = ANY(%(acciones)s)
        """.format(t=t), params)

        # 2. Los que existen: se les pone el contado.
        extra = dict(self._inv_campos_extra_quant())
        set_reason = ", reason = %(reason)s" if "reason" in extra else ""
        cr.execute("""
            WITH upd AS (
                UPDATE stock_quant q SET
                    inventory_quantity = s.cantidad,
                    inventory_diff_quantity = s.cantidad - coalesce(q.quantity, 0),
                    inventory_quantity_set = true,
                    inventory_date = %(hoy)s,
                    user_id = %(usuario)s,
                    write_uid = %(uid)s,
                    write_date = now() AT TIME ZONE 'UTC'
                    {set_reason}
                  FROM {t} s
                 WHERE s.quant_id = q.id
                   AND s.row_num BETWEEN %(desde)s AND %(hasta)s
                   AND s.accion_efectiva = 'actualizar'
                RETURNING q.id
            )
            UPDATE {t} s SET resultado_carga = 'actualizado'
              FROM upd WHERE upd.id = s.quant_id
               AND s.row_num BETWEEN %(desde)s AND %(hasta)s
        """.format(t=t, set_reason=set_reason), params)

        # 3. Los que no existen y tienen contado: quant nuevo con stock 0.
        columnas_extra = [c for c, _e in extra.items()]
        valores_extra = [e for _c, e in extra.items()]
        cr.execute("""
            WITH ins AS (
                INSERT INTO stock_quant (
                    product_id, location_id, company_id, storage_category_id,
                    quantity, reserved_quantity, inventory_quantity,
                    inventory_diff_quantity, inventory_quantity_set, inventory_date,
                    user_id, in_date, create_uid, create_date, write_uid, write_date
                    {cols_extra})
                SELECT s.product_id, s.location_id, l.company_id, l.storage_category_id,
                       0, 0, s.cantidad,
                       s.cantidad, true, %(hoy)s,
                       %(usuario)s, now() AT TIME ZONE 'UTC',
                       %(uid)s, now() AT TIME ZONE 'UTC', %(uid)s, now() AT TIME ZONE 'UTC'
                       {vals_extra}
                  FROM {t} s
                  JOIN stock_location l ON l.id = s.location_id
                  JOIN res_company c ON c.id = l.company_id
                 WHERE s.row_num BETWEEN %(desde)s AND %(hasta)s
                   AND s.accion_efectiva = 'crear'
                   AND s.quant_id IS NULL
                RETURNING id, product_id, location_id
            )
            UPDATE {t} s SET quant_id = ins.id, resultado_carga = 'creado'
              FROM ins
             WHERE ins.product_id = s.product_id AND ins.location_id = s.location_id
               AND s.row_num BETWEEN %(desde)s AND %(hasta)s
        """.format(
            t=t,
            cols_extra="".join(", %s" % c for c in columnas_extra),
            vals_extra="".join(", %s" % v for v in valores_extra),
        ), params)

        # 4. En cero y sin quant: no hay nada que crear.
        cr.execute("""
            UPDATE {t} SET resultado_carga = 'en_cero'
             WHERE row_num BETWEEN %(desde)s AND %(hasta)s
               AND accion_efectiva = 'en_cero' AND quant_id IS NULL
        """.format(t=t), params)

        # 5. Contadores y puntero.
        cr.execute("""
            SELECT count(*) FILTER (WHERE resultado_carga = 'creado'),
                   count(*) FILTER (WHERE resultado_carga = 'actualizado'),
                   count(*) FILTER (WHERE resultado_carga = 'en_cero'),
                   count(*) FILTER (WHERE accion_efectiva = 'ignorar'),
                   count(*) FILTER (WHERE accion_efectiva = 'error')
              FROM {t} WHERE row_num BETWEEN %(desde)s AND %(hasta)s
        """.format(t=t), params)
        creados, actualizados, en_cero, ignoradas, errores = cr.fetchone()
        cr.execute("""
            UPDATE {t} SET procesado = true WHERE row_num BETWEEN %(desde)s AND %(hasta)s
        """.format(t=t), params)
        procesadas = cr.rowcount

        # Los quants se tocaron por SQL: que el ORM no siga con valores viejos.
        self.env["stock.quant"].invalidate_model()
        self.write({
            "offset": min(hasta, self.total_rows),
            "processed": self.processed + procesadas,
            "quants_created": self.quants_created + creados,
            "quants_updated": self.quants_updated + actualizados,
            "quants_zero": self.quants_zero + en_cero,
            "ignored": self.ignored + ignoradas,
            "errors": self.errors + errores,
        })
        _logger.info(
            "[forum_partner_import][batch %s] carga de quants %d-%d | creados=%d "
            "actualizados=%d en_cero=%d ignoradas=%d errores=%d",
            self.id, desde, min(hasta, self.total_rows), creados, actualizados,
            en_cero, ignoradas, errores)
