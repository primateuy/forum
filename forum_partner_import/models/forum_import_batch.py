# -*- coding: utf-8 -*-
"""Importación masiva de clientes FORUM desde CSV.

El volumen (~646.000 filas) hace inviable el camino del ORM: cada create()
dispara computes, constraints y flushes por registro. Acá el CSV se carga a una
tabla staging con COPY y todo el trabajo se hace set-based en SQL, por tandas,
con commit entre tanda y tanda para que el servidor siga respondiendo y para
poder retomar desde el puntero si el proceso se corta.

El ORM se usa solo para el modelo de control, la configuración y la generación
de códigos de tarjeta (que se toma del método real de loyalty.card para que el
formato sea idéntico al que produce la UI).
"""
import csv
import logging
import os
import time
from datetime import datetime

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Nombre del CSV dentro del módulo. El módulo lee SIEMPRE este archivo.
NOMBRE_CSV = "forum_clientes_puntos_20260831.csv"
RUTA_CSV = "forum_partner_import/data/" + NOMBRE_CSV

# Columnas del CSV, en orden. El COPY las nombra explícitamente.
COLUMNAS_CSV = [
    "cedula", "nombre", "apellido", "domicilio", "telefonos", "celular",
    "departamento", "localidad", "sexo", "email", "fechanac", "en_odoo",
    "puntos", "accion",
]

# Valor exacto de la columna Acción que se ignora sin procesar.
ACCION_IGNORAR = "Ya existe - sin puntos"

# Domicilios que en el origen significan "sin dato".
DOMICILIOS_VACIOS = ("Sin dirección", "Sin direccion", "Sin Dirección", "SIN DIRECCION")


class ForumImportBatch(models.Model):
    _name = "forum.import.batch"
    _description = "Importación masiva de clientes FORUM"
    _order = "id desc"

    name = fields.Char(
        string="Nombre", required=True, default="Importación de clientes FORUM",
    )
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("loading", "Cargando staging"),
            ("ready", "Staging listo"),
            ("processing", "Procesando"),
            ("done", "Terminado"),
            ("error", "Error"),
            ("cancel", "Cancelado"),
        ],
        string="Estado", default="draft", required=True, copy=False,
    )

    # ------------------------------------------------------------------
    # Archivo de origen
    # ------------------------------------------------------------------
    file_path = fields.Char(
        string="Ruta del archivo", compute="_compute_file_info", store=False,
        help="El CSV vive dentro del módulo. No se sube por la interfaz.",
    )
    file_ok = fields.Boolean(string="Archivo accesible", compute="_compute_file_info")
    file_info = fields.Char(string="Diagnóstico del archivo", compute="_compute_file_info")

    @api.depends("state")
    def _compute_file_info(self):
        """Resuelve la ruta del CSV dentro del módulo y valida que se pueda leer.

        Se usa `tools.file_path`, que es la utilidad vigente en Odoo 17
        (`get_module_resource` ya no existe en esta versión).
        """
        for batch in self:
            ruta, ok, info = False, False, ""
            try:
                ruta = tools.file_path(RUTA_CSV)
            except Exception as e:
                info = _("No se encontró el archivo en el módulo: %s") % e
            else:
                if not os.path.isfile(ruta):
                    info = _("La ruta existe pero no es un archivo.")
                elif not os.access(ruta, os.R_OK):
                    info = _("El archivo existe pero no es legible por el usuario del servidor.")
                else:
                    tam = os.path.getsize(ruta)
                    ok = True
                    info = _("Legible. %.1f MB.") % (tam / 1024.0 / 1024.0)
            batch.file_path = ruta
            batch.file_ok = ok
            batch.file_info = info

    # ------------------------------------------------------------------
    # Configuración
    # ------------------------------------------------------------------
    reference_partner_id = fields.Many2one(
        "res.partner", string="Partner de referencia", required=True,
        help="De este contacto se toman los campos que el CSV no trae: compañía, "
             "idioma, zona horaria, país, y las propiedades por compañía si las tuviera.",
    )
    loyalty_program_id = fields.Many2one(
        "loyalty.program", string="Programa de lealtad", required=True,
        domain="[('program_type', '=', 'loyalty')]",
        help="Programa contra el que se asignan y crean las tarjetas.",
    )
    doc_type_id = fields.Many2one(
        "l10n_latam.identification.type", string="Tipo de documento", required=True,
        help="Tipo con el que se guarda la cédula en el campo NIF/vat del contacto.",
    )
    batch_size = fields.Integer(
        string="Tamaño de tanda", default=5000, required=True,
        help="Filas por tanda. Cada tanda hace commit.",
    )
    batches_per_run = fields.Integer(
        string="Tandas por corrida del cron", default=4, required=True,
    )
    points_mode = fields.Selection(
        [("overwrite", "Pisar con el valor del CSV"), ("add", "Sumar al valor actual")],
        string="Puntos en clientes existentes", default="overwrite", required=True,
    )
    backup_dir = fields.Char(
        string="Carpeta del backup", default="/tmp", required=True,
        help="Dónde se escribe el respaldo de loyalty.card antes de empezar. "
             "Debe ser escribible por el usuario del servidor.",
    )
    backup_path = fields.Char(string="Backup generado", readonly=True, copy=False)

    # ------------------------------------------------------------------
    # Avance
    # ------------------------------------------------------------------
    staging_table = fields.Char(string="Tabla staging", compute="_compute_staging_table")
    offset = fields.Integer(string="Puntero", default=0, readonly=True, copy=False)
    total_rows = fields.Integer(string="Filas totales", readonly=True, copy=False)
    processed = fields.Integer(string="Procesadas", readonly=True, copy=False)
    created = fields.Integer(string="Clientes creados", readonly=True, copy=False)
    updated = fields.Integer(string="Clientes actualizados", readonly=True, copy=False)
    ignored = fields.Integer(string="Ignoradas", readonly=True, copy=False)
    errors = fields.Integer(string="Filas con error", readonly=True, copy=False)
    cards_from_pool = fields.Integer(string="Tarjetas tomadas del pool", readonly=True, copy=False)
    cards_created = fields.Integer(string="Tarjetas creadas", readonly=True, copy=False)
    cards_updated = fields.Integer(string="Tarjetas actualizadas", readonly=True, copy=False)
    progress = fields.Float(string="Avance", compute="_compute_progress")
    started_at = fields.Datetime(
        string="Inicio del procesamiento", readonly=True, copy=False,
        help="Se sella la primera vez que arranca. Al reanudar no se pisa, para "
             "que el tiempo total refleje el proceso completo.",
    )
    ended_at = fields.Datetime(
        string="Fin del procesamiento", readonly=True, copy=False,
    )
    pool_available = fields.Integer(
        string="Tarjetas libres en el pool", compute="_compute_pool_available",
        help="Se consulta en vivo: nunca se asume un número fijo.",
    )
    error_log = fields.Text(string="Log", readonly=True, copy=False)

    @api.depends()
    def _compute_staging_table(self):
        for batch in self:
            batch.staging_table = batch._staging_name() if batch.id else False

    @api.depends("processed", "total_rows")
    def _compute_progress(self):
        for batch in self:
            batch.progress = (100.0 * batch.processed / batch.total_rows) if batch.total_rows else 0.0

    @api.depends("loyalty_program_id")
    def _compute_pool_available(self):
        """Cuenta las tarjetas libres del programa. Siempre en runtime."""
        for batch in self:
            if not batch.loyalty_program_id:
                batch.pool_available = 0
                continue
            self.env.cr.execute(
                "SELECT count(*) FROM loyalty_card WHERE program_id = %s AND partner_id IS NULL",
                (batch.loyalty_program_id.id,),
            )
            batch.pool_available = self.env.cr.fetchone()[0]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _staging_name(self):
        self.ensure_one()
        return "forum_import_staging_%d" % self.id

    def _log(self, mensaje):
        """Agrega una línea al log del batch (y al log del servidor)."""
        self.ensure_one()
        linea = "[%s] %s" % (fields.Datetime.now(), mensaje)
        _logger.info("[forum_partner_import][batch %s] %s", self.id, mensaje)
        self.sudo().write({"error_log": (self.error_log or "") + linea + "\n"})

    # ==================================================================
    # 1. Carga del staging
    # ==================================================================
    def action_cargar_staging(self):
        """Crea la tabla staging y carga el CSV con COPY, luego pre-procesa."""
        self.ensure_one()
        if self.state not in ("draft", "error", "ready"):
            raise UserError(_("Solo se puede cargar el staging desde Borrador."))
        if not self.file_ok:
            raise UserError(_("El archivo no está accesible: %s") % self.file_info)

        self.write({"state": "loading"})
        self.env.cr.commit()

        try:
            t0 = time.time()
            self._crear_staging()
            filas = self._copiar_csv()
            self._log("COPY terminado: %d filas en %.1fs" % (filas, time.time() - t0))

            t1 = time.time()
            self._preprocesar()
            self._log("Pre-procesamiento terminado en %.1fs" % (time.time() - t1))

            resumen = self._resumen_staging()
            self.write({
                "state": "ready",
                "total_rows": filas,
                "offset": 0,
                "processed": 0, "created": 0, "updated": 0, "ignored": 0, "errors": 0,
                "cards_from_pool": 0, "cards_created": 0, "cards_updated": 0,
            })
            self._log("Staging listo. " + resumen)
            self.env.cr.commit()
        except Exception as e:
            self.env.cr.rollback()
            self.write({"state": "error"})
            self._log("ERROR cargando staging: %s" % e)
            self.env.cr.commit()
            raise UserError(_("Falló la carga del staging: %s") % e)
        return True

    def _crear_staging(self):
        """Tabla UNLOGGED: no se escribe al WAL, es mucho más rápida y no hace
        falta que sobreviva a una caída del servidor (se puede recargar)."""
        t = self._staging_name()
        self.env.cr.execute("DROP TABLE IF EXISTS %s" % t)
        self.env.cr.execute("""
            CREATE UNLOGGED TABLE {t} (
                row_num           bigserial PRIMARY KEY,
                -- columnas crudas del CSV
                cedula            varchar,
                nombre            varchar,
                apellido          varchar,
                domicilio         varchar,
                telefonos         varchar,
                celular           varchar,
                departamento      varchar,
                localidad         varchar,
                sexo              varchar,
                email             varchar,
                fechanac          varchar,
                en_odoo           varchar,
                puntos            varchar,
                accion            varchar,
                -- columnas derivadas del pre-procesamiento
                nombre_completo   varchar,
                state_id          integer,
                birthdate         date,
                gender            varchar,
                puntos_int        integer,
                phone_sanitized   varchar,
                direccion_completa varchar,
                accion_efectiva   varchar,
                partner_id        integer,
                card_id           integer,
                dup_motivo        varchar,
                error             text,
                procesado         boolean DEFAULT false
            )
        """.format(t=t))
        # Índices para los joins de las tandas.
        self.env.cr.execute("CREATE INDEX %s_cedula_idx ON %s (cedula)" % (t, t))
        self.env.cr.execute("CREATE INDEX %s_pend_idx ON %s (row_num) "
                            "WHERE procesado = false" % (t, t))
        self._log("Tabla staging %s creada." % t)

    def _copiar_csv(self):
        """Carga el CSV con COPY, streameando el archivo.

        Se abre en binario y se le deja a PostgreSQL la conversión desde
        LATIN1: así el archivo no se decodifica en Python ni se carga entero
        en memoria. Los 81 MB pasan como flujo.
        """
        t = self._staging_name()
        ruta = self.file_path
        sql = """
            COPY {t} ({cols})
            FROM STDIN
            WITH (FORMAT csv, DELIMITER ';', HEADER true, ENCODING 'LATIN1', QUOTE '"')
        """.format(t=t, cols=", ".join(COLUMNAS_CSV))
        with open(ruta, "rb") as fh:
            self.env.cr.copy_expert(sql, fh)
        self.env.cr.execute("SELECT count(*) FROM %s" % t)
        return self.env.cr.fetchone()[0]

    # ==================================================================
    # 2. Pre-procesamiento (una sola pasada set-based)
    # ==================================================================
    def _preprocesar(self):
        t = self._staging_name()
        cr = self.env.cr

        # to_date tolerante: make_date sí valida (31/02 revienta en vez de
        # correrse al 3 de marzo, que es lo que hace to_date).
        cr.execute("""
            CREATE OR REPLACE FUNCTION forum_import_to_date(txt text) RETURNS date AS $$
            BEGIN
                IF txt IS NULL OR btrim(txt) !~ '^[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}$' THEN
                    RETURN NULL;
                END IF;
                RETURN make_date(
                    split_part(btrim(txt), '/', 3)::int,
                    split_part(btrim(txt), '/', 2)::int,
                    split_part(btrim(txt), '/', 1)::int);
            EXCEPTION WHEN OTHERS THEN
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql IMMUTABLE;
        """)

        # --- Limpieza y derivados ---------------------------------------
        cr.execute("""
            UPDATE {t} SET
                cedula       = NULLIF(btrim(cedula), ''),
                nombre       = NULLIF(btrim(nombre), ''),
                apellido     = NULLIF(btrim(apellido), ''),
                domicilio    = CASE WHEN btrim(coalesce(domicilio,'')) = ''
                                     OR btrim(domicilio) = ANY(%(vacios)s)
                                    THEN NULL ELSE btrim(domicilio) END,
                telefonos    = NULLIF(btrim(telefonos), ''),
                celular      = NULLIF(btrim(celular), ''),
                departamento = NULLIF(btrim(departamento), ''),
                localidad    = NULLIF(btrim(localidad), ''),
                email        = lower(NULLIF(btrim(email), '')),
                accion       = btrim(accion),
                birthdate    = forum_import_to_date(fechanac),
                -- "Desconocido" es ausencia de dato, no un valor: queda NULL.
                gender       = CASE lower(btrim(coalesce(sexo,'')))
                                    WHEN 'femenino'  THEN 'female'
                                    WHEN 'masculino' THEN 'male'
                                    ELSE NULL END,
                puntos_int   = CASE WHEN btrim(coalesce(puntos,'')) ~ '^-?[0-9]+$'
                                    THEN btrim(puntos)::int ELSE 0 END
        """.format(t=t), {"vacios": list(DOMICILIOS_VACIOS)})

        # Nombre visible: "Nombre Apellido", tolerando Nombre vacío.
        cr.execute("""
            UPDATE {t} SET
                nombre_completo = btrim(concat_ws(' ', nombre, apellido))
        """.format(t=t))

        # Marcar filas sin apellido ni nombre: el constraint _check_name de
        # partner_firstname exige al menos uno.
        cr.execute("""
            UPDATE {t} SET error = 'Sin nombre ni apellido'
            WHERE nombre IS NULL AND apellido IS NULL
        """.format(t=t))

        # Cédula obligatoria: es la clave de matching.
        cr.execute("""
            UPDATE {t} SET error = coalesce(error || ' | ', '') || 'Cédula vacía'
            WHERE cedula IS NULL
        """.format(t=t))

        # --- Departamento -> res.country.state ---------------------------
        # unaccent está instalado; los departamentos vienen sin tildes.
        cr.execute("""
            UPDATE {t} s SET state_id = st.id
            FROM res_country_state st
            JOIN res_country c ON c.id = st.country_id AND c.code = 'UY'
            WHERE s.departamento IS NOT NULL
              AND unaccent(lower(s.departamento)) = unaccent(lower(st.name))
        """.format(t=t))

        # --- phone_sanitized (mismo resultado que phone_validation para UY) ---
        # El compute real toma el primer número no vacío entre mobile y phone.
        cr.execute("""
            UPDATE {t} SET phone_sanitized = (
                CASE
                    WHEN coalesce(celular, telefonos) IS NULL THEN NULL
                    WHEN regexp_replace(coalesce(celular, telefonos), '\\D', '', 'g') = '' THEN NULL
                    WHEN regexp_replace(coalesce(celular, telefonos), '\\D', '', 'g') LIKE '598%%'
                        THEN '+' || regexp_replace(coalesce(celular, telefonos), '\\D', '', 'g')
                    WHEN length(regexp_replace(coalesce(celular, telefonos), '\\D', '', 'g')) = 8
                        THEN '+598' || regexp_replace(coalesce(celular, telefonos), '\\D', '', 'g')
                    ELSE '+' || regexp_replace(coalesce(celular, telefonos), '\\D', '', 'g')
                END)
        """.format(t=t))

        # --- contact_address_complete (stored computed de res.partner) ----
        # Formato observado en los partners existentes de esta base:
        # "calle, ciudad, departamento, país", salteando los vacíos.
        cr.execute("""
            UPDATE {t} s SET direccion_completa = NULLIF(concat_ws(', ',
                    s.domicilio,
                    s.localidad,
                    st.name,
                    %(pais)s
                ), '')
            FROM {t} s2
            LEFT JOIN res_country_state st ON st.id = s2.state_id
            WHERE s2.row_num = s.row_num
        """.format(t=t), {"pais": self.reference_partner_id.country_id.name or None})

        # --- Matching contra res_partner REAL ----------------------------
        # No se confía en la columna "En Odoo" del CSV: la base pudo cambiar
        # desde que se generó el archivo. La acción efectiva sale de esta
        # verificación.
        #
        # Desempate de cédulas duplicadas en la base: gana el partner que YA
        # tiene tarjeta en el programa (así no se le crea una segunda tarjeta
        # a la misma cédula a través de su duplicado). Si ninguno o varios
        # tienen tarjeta, gana el id más chico.
        cr.execute("""
            WITH candidatos AS (
                SELECT p.id, p.vat,
                       EXISTS (SELECT 1 FROM loyalty_card c
                                WHERE c.partner_id = p.id
                                  AND c.program_id = %(program)s) AS tiene_card
                  FROM res_partner p
                 WHERE p.l10n_latam_identification_type_id = %(doc_type)s
                   AND p.vat IS NOT NULL AND p.vat <> ''
            ),
            rankeados AS (
                SELECT vat, id, tiene_card,
                       ROW_NUMBER() OVER (PARTITION BY vat
                                          ORDER BY tiene_card DESC, id ASC) AS rn,
                       COUNT(*)      OVER (PARTITION BY vat) AS n_cand,
                       COUNT(*) FILTER (WHERE tiene_card)
                                     OVER (PARTITION BY vat) AS n_con_card
                  FROM candidatos
            )
            UPDATE {t} s SET
                partner_id = r.id,
                dup_motivo = CASE
                    WHEN r.n_cand = 1 THEN NULL
                    WHEN r.n_con_card = 1 THEN
                        'cedula duplicada en la base (' || r.n_cand || ' partners): '
                        || 'elegido id ' || r.id || ' por ser el unico con tarjeta'
                    ELSE
                        'cedula duplicada en la base (' || r.n_cand || ' partners, '
                        || r.n_con_card || ' con tarjeta): elegido id ' || r.id
                        || ' por ser el menor id'
                    END
              FROM rankeados r
             WHERE r.rn = 1
               AND s.cedula = r.vat
        """.format(t=t), {"program": self.loyalty_program_id.id,
                          "doc_type": self.doc_type_id.id})

        # --- Acción efectiva --------------------------------------------
        cr.execute("""
            UPDATE {t} SET accion_efectiva = CASE
                WHEN error IS NOT NULL           THEN 'error'
                WHEN accion = %(ignorar)s        THEN 'ignorar'
                WHEN partner_id IS NOT NULL      THEN 'actualizar'
                ELSE                                  'crear'
            END
        """.format(t=t), {"ignorar": ACCION_IGNORAR})

        cr.execute("ANALYZE %s" % t)

    def _resumen_staging(self):
        """Texto con el reparto de acciones efectivas y las discrepancias."""
        t = self._staging_name()
        cr = self.env.cr
        cr.execute("""
            SELECT accion_efectiva, count(*) FROM {t} GROUP BY 1 ORDER BY 1
        """.format(t=t))
        reparto = ", ".join("%s=%s" % (a, n) for a, n in cr.fetchall())

        cr.execute("""
            SELECT count(*) FROM {t}
             WHERE accion_efectiva <> 'error'
               AND ((accion IN (%s, 'Actualizar puntos') AND partner_id IS NULL)
                 OR (accion NOT IN (%s, 'Actualizar puntos') AND partner_id IS NOT NULL))
        """.format(t=t), (ACCION_IGNORAR, ACCION_IGNORAR))
        discrepancias = cr.fetchone()[0]

        cr.execute("SELECT count(*) FROM %s WHERE dup_motivo IS NOT NULL" % t)
        duplicados = cr.fetchone()[0]

        cr.execute("""
            SELECT count(*) FROM {t}
             WHERE puntos_int > 0 AND accion_efectiva IN ('crear', 'actualizar')
        """.format(t=t))
        con_puntos = cr.fetchone()[0]

        cr.execute("SELECT count(*) FROM %s WHERE state_id IS NULL AND departamento IS NOT NULL" % t)
        sin_state = cr.fetchone()[0]

        return (u"Acciones efectivas: %s. Discrepancias con la columna 'Acción' del CSV: %d. "
                u"Cédulas duplicadas en la base resueltas: %d. Filas con puntos > 0: %d. "
                u"Filas sin departamento resuelto: %d."
                % (reparto, discrepancias, duplicados, con_puntos, sin_state))

    # ==================================================================
    # 3. Backup obligatorio de las tarjetas
    # ==================================================================
    def _hacer_backup_tarjetas(self):
        """Respalda loyalty_card del programa a un CSV en el filesystem.

        Asignar una tarjeta del pool pisa los puntos que traía. Este respaldo
        es la única forma de volver atrás, así que si falla no se arranca.
        Devuelve la ruta escrita.
        """
        self.ensure_one()
        carpeta = (self.backup_dir or "").strip() or "/tmp"

        if not os.path.isdir(carpeta):
            raise UserError(_("La carpeta de backup no existe: %s") % carpeta)
        if not os.access(carpeta, os.W_OK):
            raise UserError(_("La carpeta de backup no es escribible: %s") % carpeta)

        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta = os.path.join(
            carpeta, "loyalty_card_backup_prog%d_%s.csv" % (self.loyalty_program_id.id, sello))

        try:
            with open(ruta, "wb") as fh:
                self.env.cr.copy_expert(
                    """COPY (SELECT id, code, points, partner_id, program_id
                               FROM loyalty_card
                              WHERE program_id = %d
                              ORDER BY id)
                       TO STDOUT WITH (FORMAT csv, HEADER true)""" % self.loyalty_program_id.id,
                    fh,
                )
        except Exception as e:
            raise UserError(_("No se pudo escribir el backup de tarjetas en %s: %s") % (ruta, e))

        if not os.path.isfile(ruta) or os.path.getsize(ruta) == 0:
            raise UserError(_("El backup de tarjetas quedó vacío o no se creó: %s") % ruta)

        filas = 0
        with open(ruta, "r", encoding="utf-8") as fh:
            filas = max(sum(1 for _l in fh) - 1, 0)

        self.write({"backup_path": ruta})
        self._log("Backup de tarjetas escrito: %s (%d tarjetas, %.1f KB)"
                  % (ruta, filas, os.path.getsize(ruta) / 1024.0))
        return ruta

    def action_backup_tarjetas(self):
        """Botón: genera el backup sin arrancar el procesamiento."""
        self.ensure_one()
        self._hacer_backup_tarjetas()
        self.env.cr.commit()
        return self._notificar(_("Backup generado"), self.backup_path)

    # ==================================================================
    # 4. Arranque del procesamiento
    # ==================================================================
    def action_iniciar(self):
        """Valida, respalda las tarjetas y deja el batch listo para el cron."""
        self.ensure_one()
        if self.state not in ("ready", "processing"):
            raise UserError(_("Primero hay que cargar el staging."))
        if not self._staging_existe():
            raise UserError(_("No existe la tabla staging %s. Volvé a cargarla.")
                            % self._staging_name())
        if self.batch_size < 1:
            raise UserError(_("El tamaño de tanda debe ser mayor a cero."))

        # Paso previo obligatorio: si el backup falla, no se arranca.
        if not self.backup_path or not os.path.isfile(self.backup_path):
            self._hacer_backup_tarjetas()

        vals = {"state": "processing", "ended_at": False}
        if not self.started_at:
            vals["started_at"] = fields.Datetime.now()
        self.write(vals)
        cron = self.env.ref("forum_partner_import.ir_cron_forum_partner_import",
                            raise_if_not_found=False)
        if cron:
            cron.sudo().write({"active": True})
            cron.sudo()._trigger()
        self._log("Procesamiento iniciado. Puntero en %d de %d."
                  % (self.offset, self.total_rows))
        self.env.cr.commit()
        # Se devuelve True a propósito, sin acción de notificación: cuando un
        # botón no devuelve acción, el formulario recarga el registro, y esa
        # recarga es la que hace que el widget de avance vea el estado
        # 'processing' y arranque el polling. Con una notificación de por medio
        # el registro del cliente se quedaba en 'ready' y la barra no se movía.
        return True

    def action_cancelar(self):
        self.ensure_one()
        self.write({"state": "cancel", "ended_at": fields.Datetime.now()})
        self._log("Cancelado por el usuario en la fila %d." % self.offset)
        return True

    def action_reanudar(self):
        self.ensure_one()
        if self.state not in ("cancel", "error"):
            raise UserError(_("Solo se reanuda un batch cancelado o con error."))
        vals = {"state": "processing", "ended_at": False}
        if not self.started_at:
            vals["started_at"] = fields.Datetime.now()
        self.write(vals)
        self._log("Reanudado desde la fila %d." % self.offset)
        cron = self.env.ref("forum_partner_import.ir_cron_forum_partner_import",
                            raise_if_not_found=False)
        if cron:
            cron.sudo().write({"active": True})
            cron.sudo()._trigger()
        return True

    def _staging_existe(self):
        self.ensure_one()
        self.env.cr.execute("SELECT to_regclass(%s)", (self._staging_name(),))
        return bool(self.env.cr.fetchone()[0])

    def _notificar(self, titulo, mensaje):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": titulo, "message": mensaje,
                       "type": "success", "sticky": False},
        }

    # ==================================================================
    # 5. Procesamiento por tandas
    # ==================================================================
    @api.model
    def _cron_procesar(self):
        """Cron: avanza los batches en curso y se autodesactiva si no hay."""
        pendientes = self.search([("state", "=", "processing")], order="id")
        if not pendientes:
            cron = self.env.ref("forum_partner_import.ir_cron_forum_partner_import",
                                raise_if_not_found=False)
            if cron:
                cron.sudo().write({"active": False})
            return True

        for batch in pendientes:
            batch._procesar_varias_tandas()
        return True

    def _procesar_varias_tandas(self):
        """Procesa `batches_per_run` tandas, con commit después de cada una."""
        self.ensure_one()
        for _i in range(max(self.batches_per_run, 1)):
            # Se relee el estado por si lo cancelaron desde la interfaz
            # mientras corría la tanda anterior.
            self.invalidate_recordset(["state", "offset"])
            if self.state != "processing":
                return
            if self.offset >= self.total_rows:
                self._finalizar()
                return
            try:
                self._procesar_tanda()
                self.env.cr.commit()
            except Exception as e:
                self.env.cr.rollback()
                self.write({"state": "error", "ended_at": fields.Datetime.now()})
                self._log("ERROR en la tanda que arranca en %d: %s" % (self.offset, e))
                self.env.cr.commit()
                _logger.exception("[forum_partner_import] tanda fallida")
                return

        # Si ya no quedan filas se cierra acá mismo. Sin esto la pantalla se
        # queda mostrando "Procesando" al 100% hasta el tick siguiente del
        # cron, que es confuso: parece colgado cuando en realidad terminó.
        self.invalidate_recordset(["offset"])
        if self.offset >= self.total_rows:
            self._finalizar()
            return

        # Quedan filas: se reencola para seguir sin esperar al próximo tick.
        cron = self.env.ref("forum_partner_import.ir_cron_forum_partner_import",
                            raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    def _procesar_tanda(self):
        """Procesa una tanda de `batch_size` filas."""
        self.ensure_one()
        t0 = time.time()
        desde = self.offset + 1
        hasta = self.offset + self.batch_size
        t = self._staging_name()
        cr = self.env.cr
        uid = self.env.uid

        params = {
            "desde": desde, "hasta": hasta,
            "uid": uid,
            "program": self.loyalty_program_id.id,
            "doc_type": self.doc_type_id.id,
        }

        # ---- 5.1 Clientes nuevos -----------------------------------------
        creados = self._insertar_partners(t, params)

        # ---- 5.2 Propiedades por compañía del partner de referencia ------
        self._copiar_propiedades(t, params)

        # ---- 5.3 Tarjetas ------------------------------------------------
        del_pool, nuevas, actualizadas = self._procesar_tarjetas(t, params)

        # ---- 5.4 Contadores y puntero ------------------------------------
        cr.execute("""
            SELECT accion_efectiva, count(*) FROM {t}
             WHERE row_num BETWEEN %(desde)s AND %(hasta)s
             GROUP BY 1
        """.format(t=t), params)
        reparto = dict(cr.fetchall())

        cr.execute("""
            UPDATE {t} SET procesado = true
             WHERE row_num BETWEEN %(desde)s AND %(hasta)s
        """.format(t=t), params)
        procesadas = cr.rowcount

        self.write({
            "offset": min(hasta, self.total_rows),
            "processed": self.processed + procesadas,
            "created": self.created + creados,
            "updated": self.updated + reparto.get("actualizar", 0),
            "ignored": self.ignored + reparto.get("ignorar", 0),
            "errors": self.errors + reparto.get("error", 0),
            "cards_from_pool": self.cards_from_pool + del_pool,
            "cards_created": self.cards_created + nuevas,
            "cards_updated": self.cards_updated + actualizadas,
        })

        _logger.info(
            "[forum_partner_import][batch %s] tanda %d-%d en %.2fs | "
            "creados=%d actualizados=%d ignorados=%d errores=%d | "
            "tarjetas pool=%d nuevas=%d actualizadas=%d",
            self.id, desde, min(hasta, self.total_rows), time.time() - t0,
            creados, reparto.get("actualizar", 0), reparto.get("ignorar", 0),
            reparto.get("error", 0), del_pool, nuevas, actualizadas,
        )

    def _finalizar(self):
        """Post-proceso liviano al terminar todas las tandas."""
        self.ensure_one()
        self.write({"state": "done", "ended_at": fields.Datetime.now()})
        self.env.registry.clear_cache()
        self._log("Terminado. Creados=%d Actualizados=%d Ignorados=%d Errores=%d | "
                  "Tarjetas: pool=%d nuevas=%d actualizadas=%d"
                  % (self.created, self.updated, self.ignored, self.errors,
                     self.cards_from_pool, self.cards_created, self.cards_updated))
        if self.errors:
            self._log("La tabla staging %s se conserva porque hubo filas con error."
                      % self._staging_name())
        self.env.cr.commit()

    # ==================================================================
    # 6. INSERT de clientes nuevos
    # ==================================================================
    def _insertar_partners(self, t, params):
        """Inserta los partners de la tanda en una sola sentencia.

        Los ids se piden de antemano a la secuencia y se guardan en staging.
        Eso evita depender de RETURNING para correlacionar (que no puede
        devolver columnas de staging) y permite setear commercial_partner_id
        con el propio id en el mismo INSERT, sin un UPDATE posterior.
        """
        cr = self.env.cr
        ref = self.reference_partner_id

        cr.execute("""
            UPDATE {t} SET partner_id = nextval('res_partner_id_seq')
             WHERE row_num BETWEEN %(desde)s AND %(hasta)s
               AND accion_efectiva = 'crear'
               AND partner_id IS NULL
        """.format(t=t), params)
        a_crear = cr.rowcount
        if not a_crear:
            return 0

        vals = dict(params)
        vals.update({
            "company_id": ref.company_id.id or None,
            "lang": ref.lang or None,
            "tz": ref.tz or None,
            "country_id": ref.country_id.id or None,
        })

        # Los campos calculados stored de res.partner se setean a mano porque
        # el ORM no interviene: name (es computed de firstname/lastname por
        # partner_firstname), complete_name, commercial_partner_id,
        # partner_share, email_normalized, phone_sanitized y
        # contact_address_complete.
        cr.execute("""
            INSERT INTO res_partner (
                id, name, firstname, lastname, complete_name,
                commercial_partner_id, partner_share,
                active, type, is_company, color, customer_rank, supplier_rank,
                company_id, lang, tz, country_id, state_id, city, street,
                phone, mobile, email, email_normalized, phone_sanitized,
                contact_address_complete,
                vat, l10n_latam_identification_type_id,
                birthdate_date, gender,
                vies_valid, pos_fe_max_amount_company_currency,
                create_uid, write_uid, create_date, write_date
            )
            SELECT
                s.partner_id,
                s.nombre_completo, s.nombre, s.apellido, s.nombre_completo,
                s.partner_id, true,
                true, 'contact', false, 0, 1, 0,
                %(company_id)s, %(lang)s, %(tz)s, %(country_id)s,
                s.state_id, s.localidad, s.domicilio,
                s.telefonos, s.celular, s.email, s.email, s.phone_sanitized,
                s.direccion_completa,
                s.cedula, %(doc_type)s,
                s.birthdate, s.gender,
                -- El ORM calcula false/0 para estos dos en contactos de persona
                -- física; se setean explícitos para que la fila quede idéntica
                -- a una creada por Odoo y no NULL.
                false, 0.0,
                %(uid)s, %(uid)s, now() AT TIME ZONE 'utc', now() AT TIME ZONE 'utc'
              FROM {t} s
             WHERE s.row_num BETWEEN %(desde)s AND %(hasta)s
               AND s.accion_efectiva = 'crear'
               AND s.partner_id IS NOT NULL
        """.format(t=t), vals)
        return cr.rowcount

    def _copiar_propiedades(self, t, params):
        """Replica las propiedades por compañía del partner de referencia.

        En Odoo 17 los campos company-dependent viven en ir_property. Solo se
        copian si el partner de referencia tiene valores propios; si usa los
        defaults de la compañía no hay nada que hacer y no se toca nada.
        """
        cr = self.env.cr
        ref_key = "res.partner,%d" % self.reference_partner_id.id

        cr.execute("SELECT count(*) FROM ir_property WHERE res_id = %s", (ref_key,))
        if not cr.fetchone()[0]:
            return 0

        cr.execute("""
            INSERT INTO ir_property (
                name, res_id, company_id, fields_id, value_float, value_integer,
                value_text, value_binary, value_reference, value_datetime, type,
                create_uid, write_uid, create_date, write_date
            )
            SELECT p.name,
                   'res.partner,' || s.partner_id,
                   p.company_id, p.fields_id, p.value_float, p.value_integer,
                   p.value_text, p.value_binary, p.value_reference, p.value_datetime,
                   p.type,
                   %(uid)s, %(uid)s, now() AT TIME ZONE 'utc', now() AT TIME ZONE 'utc'
              FROM ir_property p
             CROSS JOIN {t} s
             WHERE p.res_id = %(ref_key)s
               AND s.row_num BETWEEN %(desde)s AND %(hasta)s
               AND s.accion_efectiva = 'crear'
               AND s.partner_id IS NOT NULL
        """.format(t=t), dict(params, ref_key=ref_key))
        return cr.rowcount

    # ==================================================================
    # 7. Tarjetas de lealtad
    # ==================================================================
    def _procesar_tarjetas(self, t, params):
        """Resuelve las tarjetas de la tanda.

        Orden: primero se actualizan las de clientes que ya tenían tarjeta,
        después se reparte el pool de tarjetas libres, y lo que sobra se crea.
        La transición pool -> creación puede caer en el medio de la tanda.

        Las filas con Puntos = 0 no tocan loyalty en absoluto.
        """
        actualizadas = self._actualizar_tarjetas_existentes(t, params)
        del_pool = self._asignar_desde_pool(t, params)
        nuevas = self._crear_tarjetas(t, params)
        return del_pool, nuevas, actualizadas

    def _actualizar_tarjetas_existentes(self, t, params):
        """Clientes que ya existían y ya tenían tarjeta: se pisan/suman puntos.

        Si un cliente tuviera más de una tarjeta en el programa se toma la de
        menor id, para no repartir los puntos entre varias.
        """
        cr = self.env.cr

        cr.execute("""
            UPDATE {t} s SET card_id = c.id
              FROM (SELECT partner_id, MIN(id) AS id
                      FROM loyalty_card
                     WHERE program_id = %(program)s AND partner_id IS NOT NULL
                     GROUP BY partner_id) c
             WHERE s.row_num BETWEEN %(desde)s AND %(hasta)s
               AND s.accion_efectiva = 'actualizar'
               AND s.puntos_int > 0
               AND s.card_id IS NULL
               AND s.partner_id = c.partner_id
        """.format(t=t), params)

        modo_suma = self.points_mode == "add"
        cr.execute("""
            UPDATE loyalty_card c
               SET points = CASE WHEN %(suma)s THEN coalesce(c.points, 0) + s.puntos_int
                                 ELSE s.puntos_int END,
                   write_uid = %(uid)s,
                   write_date = now() AT TIME ZONE 'utc'
              FROM {t} s
             WHERE s.row_num BETWEEN %(desde)s AND %(hasta)s
               AND s.accion_efectiva = 'actualizar'
               AND s.puntos_int > 0
               AND s.card_id = c.id
        """.format(t=t), dict(params, suma=modo_suma))
        return cr.rowcount

    def _pendientes_de_tarjeta(self, t, params):
        """Cuántas filas de la tanda necesitan una tarjeta que todavía no tienen."""
        self.env.cr.execute("""
            SELECT count(*) FROM {t}
             WHERE row_num BETWEEN %(desde)s AND %(hasta)s
               AND accion_efectiva IN ('crear', 'actualizar')
               AND puntos_int > 0
               AND partner_id IS NOT NULL
               AND card_id IS NULL
        """.format(t=t), params)
        return self.env.cr.fetchone()[0]

    def _asignar_desde_pool(self, t, params):
        """Reparte las tarjetas libres del programa entre las filas pendientes.

        Emparejamiento por posición: ROW_NUMBER() sobre las tarjetas libres
        contra ROW_NUMBER() sobre las filas pendientes. Las tarjetas se toman
        de las más viejas (id ASC) y con FOR UPDATE SKIP LOCKED, para que dos
        procesos concurrentes no se peleen la misma tarjeta.

        El pool se consulta en vivo en cada tanda: nunca se asume un tamaño.
        """
        necesarias = self._pendientes_de_tarjeta(t, params)
        if not necesarias:
            return 0

        cr = self.env.cr
        cr.execute("""
            WITH pick AS (
                SELECT id
                  FROM loyalty_card
                 WHERE program_id = %(program)s
                   AND partner_id IS NULL
                 ORDER BY id
                 LIMIT %(necesarias)s
                 FOR UPDATE SKIP LOCKED
            ),
            libres AS (
                SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS rn FROM pick
            ),
            pendientes AS (
                SELECT row_num, partner_id, puntos_int,
                       ROW_NUMBER() OVER (ORDER BY row_num) AS rn
                  FROM {t}
                 WHERE row_num BETWEEN %(desde)s AND %(hasta)s
                   AND accion_efectiva IN ('crear', 'actualizar')
                   AND puntos_int > 0
                   AND partner_id IS NOT NULL
                   AND card_id IS NULL
            ),
            asignacion AS (
                SELECT l.id AS card_id, p.row_num, p.partner_id, p.puntos_int
                  FROM libres l
                  JOIN pendientes p USING (rn)
            ),
            tocar_tarjeta AS (
                UPDATE loyalty_card c
                   SET partner_id = a.partner_id,
                       points = a.puntos_int,
                       write_uid = %(uid)s,
                       write_date = now() AT TIME ZONE 'utc'
                  FROM asignacion a
                 WHERE c.id = a.card_id
                RETURNING c.id
            )
            UPDATE {t} s
               SET card_id = a.card_id
              FROM asignacion a
             WHERE s.row_num = a.row_num
        """.format(t=t), dict(params, necesarias=necesarias))
        return cr.rowcount

    def _generar_codigos(self, cantidad):
        """Genera `cantidad` códigos únicos con el generador real de Odoo.

        Se llama a `loyalty.card._generate_code()`, que es el mismo método que
        usa la interfaz al crear una tarjeta a mano ('044' + un tramo del
        uuid4). Así el formato es idéntico, no una imitación.

        La unicidad se verifica contra la base y contra el propio lote, y las
        colisiones se regeneran.
        """
        Card = self.env["loyalty.card"]
        codigos = set()
        intentos = 0
        while len(codigos) < cantidad:
            intentos += 1
            if intentos > 20:
                raise UserError(
                    _("No se pudieron generar %d códigos únicos de tarjeta "
                      "después de %d intentos.") % (cantidad, intentos))
            faltan = cantidad - len(codigos)
            candidatos = {Card._generate_code() for _i in range(faltan)}
            candidatos -= codigos
            if not candidatos:
                continue
            self.env.cr.execute(
                "SELECT code FROM loyalty_card WHERE code = ANY(%s)",
                (list(candidatos),))
            ocupados = {r[0] for r in self.env.cr.fetchall()}
            nuevos = candidatos - ocupados
            if ocupados:
                _logger.info("[forum_partner_import] %d códigos colisionaron, "
                             "se regeneran", len(ocupados))
            codigos |= nuevos
        return list(codigos)

    def _crear_tarjetas(self, t, params):
        """Crea tarjetas nuevas para lo que el pool no alcanzó a cubrir."""
        cr = self.env.cr
        cr.execute("""
            SELECT row_num FROM {t}
             WHERE row_num BETWEEN %(desde)s AND %(hasta)s
               AND accion_efectiva IN ('crear', 'actualizar')
               AND puntos_int > 0
               AND partner_id IS NOT NULL
               AND card_id IS NULL
             ORDER BY row_num
        """.format(t=t), params)
        filas = [r[0] for r in cr.fetchall()]
        if not filas:
            return 0

        codigos = self._generar_codigos(len(filas))

        # Ids pedidos por adelantado, igual que con los partners.
        cr.execute("SELECT nextval('loyalty_card_id_seq') FROM generate_series(1, %s)",
                   (len(filas),))
        ids = [r[0] for r in cr.fetchall()]

        datos = list(zip(filas, ids, codigos))

        from psycopg2.extras import execute_values
        execute_values(
            cr._obj,
            """
            INSERT INTO loyalty_card (
                id, program_id, partner_id, points, code, company_id,
                create_uid, write_uid, create_date, write_date
            )
            SELECT v.card_id, %(program)s, s.partner_id, s.puntos_int, v.code,
                   %(company)s,
                   %(uid)s, %(uid)s, now() AT TIME ZONE 'utc', now() AT TIME ZONE 'utc'
              FROM (VALUES %%s) AS v(row_num, card_id, code)
              JOIN {t} s ON s.row_num = v.row_num
            """.format(t=t) % {
                "program": self.loyalty_program_id.id,
                "company": self.loyalty_program_id.company_id.id or "NULL",
                "uid": self.env.uid,
            },
            datos,
            template="(%s, %s, %s)",
            page_size=1000,
        )
        creadas = len(datos)

        execute_values(
            cr._obj,
            "UPDATE {t} s SET card_id = v.card_id "
            "FROM (VALUES %s) AS v(row_num, card_id) "
            "WHERE s.row_num = v.row_num".format(t=t),
            [(f, i) for f, i, _c in datos],
            template="(%s, %s)",
            page_size=1000,
        )
        return creadas

    # ==================================================================
    # 8. Utilidades de cierre
    # ==================================================================
    def action_exportar_errores(self):
        """Exporta a CSV las filas de staging que quedaron con error."""
        self.ensure_one()
        if not self._staging_existe():
            raise UserError(_("Ya no existe la tabla staging de este batch."))

        carpeta = (self.backup_dir or "/tmp").strip()
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta = os.path.join(carpeta, "forum_import_errores_%d_%s.csv" % (self.id, sello))
        t = self._staging_name()
        with open(ruta, "wb") as fh:
            self.env.cr.copy_expert("""
                COPY (SELECT row_num, cedula, nombre, apellido, accion,
                             accion_efectiva, dup_motivo, error
                        FROM {t}
                       WHERE error IS NOT NULL
                       ORDER BY row_num)
                TO STDOUT WITH (FORMAT csv, HEADER true)
            """.format(t=t), fh)
        self._log("Errores exportados a %s" % ruta)
        return self._notificar(_("Errores exportados"), ruta)

    def action_exportar_duplicados(self):
        """Exporta las cédulas duplicadas en la base y cómo se resolvieron."""
        self.ensure_one()
        if not self._staging_existe():
            raise UserError(_("Ya no existe la tabla staging de este batch."))

        carpeta = (self.backup_dir or "/tmp").strip()
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta = os.path.join(carpeta, "forum_import_duplicados_%d_%s.csv" % (self.id, sello))
        t = self._staging_name()
        with open(ruta, "wb") as fh:
            self.env.cr.copy_expert("""
                COPY (SELECT cedula, partner_id, dup_motivo
                        FROM {t}
                       WHERE dup_motivo IS NOT NULL
                       ORDER BY cedula)
                TO STDOUT WITH (FORMAT csv, HEADER true)
            """.format(t=t), fh)
        self._log("Duplicados exportados a %s" % ruta)
        return self._notificar(_("Duplicados exportados"), ruta)

    def action_drop_staging(self):
        """Borra la tabla staging. Se pide confirmación desde la vista."""
        self.ensure_one()
        if self.state == "processing":
            raise UserError(_("No se puede borrar el staging mientras se procesa."))
        self.env.cr.execute("DROP TABLE IF EXISTS %s" % self._staging_name())
        self._log("Tabla staging borrada.")
        return True

    def unlink(self):
        """Al borrar el batch se lleva su tabla staging."""
        for batch in self:
            if batch.state == "processing":
                raise UserError(_("No se puede borrar un batch en procesamiento."))
            self.env.cr.execute("DROP TABLE IF EXISTS %s" % batch._staging_name())
        return super().unlink()
