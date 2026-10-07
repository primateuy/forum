-- Dump de un endpoint de la API de consultas (odoo_api_query) para un rango de
-- fechas, para que Heinwiss rellene un período que no sincronizó. SÓLO LECTURA.
--
-- Variables (psql -v):
--   qkey   06_invoice_details | 07_invoices | 15_stock_movements
--   desde  inclusive, 'YYYY-MM-DD HH24:MI:SS'
--   hasta  exclusive, mismo formato
-- Se comparan contra cada campo tal como lo hace la API, que es distinto según
-- el endpoint (ver README.md, «Qué abarca el rango»).
--
-- El SQL NO está copiado acá: se lee de api_query_definition en la misma base y
-- se le agrega el filtro de fechas del mismo modo que el controlador
-- (base_sql + " AND campo op %s"), con el mismo campo que usa Heinwiss en sus
-- llamadas a cada endpoint (sacado de api_query_log):
--   06_invoice_details  cfe_fecha_hora_firma
--   07_invoices         invoice_local_date
--   15_stock_movements  stock_movement_local_date
-- Sin LIMIT/OFFSET. Mismas filas, columnas y valores que la API, escritos como
-- los devuelve la API (lo resuelve a_csv.py).
--
-- Todo lo informativo sale por stderr (\warn); stdout lleva sólo los datos.
-- Requiere psql 13+. Uso en README.md.

\set ON_ERROR_STOP 1
SET default_transaction_read_only = on;
SET statement_timeout = '15min';
-- La zona horaria NO se fija: Odoo tampoco la fija en su conexión, así que la
-- API usa la del servidor PostgreSQL, y esta sesión también (siempre que no
-- haya PGTZ en el entorno). Importa para 07_invoices: invoice_local_date es
-- to_char(cfe_fecha_hora_firma::timestamptz), o sea la firma (texto con huso
-- -03:00) expresada en la zona de la sesión. Se informa en el log.
SELECT current_setting('TimeZone') AS zona \gset

\if :{?qkey}
\else
  \warn 'ERROR: falta -v qkey=...'
  SELECT 1/0 AS falta_qkey;
\endif
\if :{?desde}
\else
  \warn 'ERROR: falta -v desde=...'
  SELECT 1/0 AS falta_desde;
\endif
\if :{?hasta}
\else
  \warn 'ERROR: falta -v hasta=...'
  SELECT 1/0 AS falta_hasta;
\endif

-- 1. Campo de fecha del endpoint -------------------------------------------
SELECT COALESCE(CASE :'qkey'
         WHEN '06_invoice_details' THEN 'cfe_fecha_hora_firma'
         WHEN '07_invoices' THEN 'invoice_local_date'
         WHEN '15_stock_movements' THEN 'stock_movement_local_date'
       END, '') AS campo_fecha \gset
SELECT :'campo_fecha' <> '' AS campo_ok \gset
\if :campo_ok
\else
  \warn 'ERROR: qkey no soportado (06_invoice_details, 07_invoices, 15_stock_movements).'
  SELECT 1/0 AS qkey_no_soportado;
\endif

-- 2. La consulta guardada --------------------------------------------------
SELECT to_regclass('public.api_query_definition') IS NOT NULL AS existe_tabla \gset
\if :existe_tabla
\else
  \warn 'ERROR: no existe api_query_definition en esta base (¿copia vieja del PostgreSQL local del servidor?).'
  SELECT 1/0 AS no_existe_api_query_definition;
\endif

SELECT count(*) = 1 AS una_sola
  FROM api_query_definition WHERE query_key = :'qkey' AND active \gset
\if :una_sola
\else
  \warn 'ERROR: no hay exactamente una definición activa para esa query_key.'
  SELECT 1/0 AS definicion_ambigua;
\endif

SELECT btrim(sql_query) AS base_sql,
       md5(btrim(sql_query)) AS base_md5,
       name AS def_name,
       to_char(write_date, 'YYYY-MM-DD HH24:MI:SS') AS def_write_date
  FROM api_query_definition WHERE query_key = :'qkey' AND active \gset

\warn '--------------------------------------------------------------------'
\warn 'base:       ' :DBNAME
\warn 'endpoint:   ' :qkey ' (' :def_name ')'
\warn 'definición: md5 ' :base_md5 ', modificada ' :def_write_date ' UTC'
\warn 'filtro:     ' :campo_fecha ' >= ' :desde ' AND ' :campo_fecha ' < ' :hasta
\warn 'zona:       ' :zona ' (la de la sesión, igual que la API)'
\warn '--------------------------------------------------------------------'

-- 3. Exportación -----------------------------------------------------------
-- Igual que el controlador: el filtro se pega al final del SQL guardado (todas
-- las definiciones de estos tres endpoints terminan en un WHERE). El salto de
-- línea antes del AND evita que un comentario '--' en la última línea se coma
-- el filtro.
--
-- stdout NO es el CSV: son los tipos de las columnas (\gdesc), una línea
-- marcadora y una fila JSON por línea. a_csv.py lo convierte al CSV con los
-- valores escritos como los devuelve la API, que necesita el tipo de cada
-- columna (numeric → float, timestamp → isoformat).
\pset format unaligned
\pset tuples_only on
\pset fieldsep '\t'
\pset null ''
SELECT * FROM (
:base_sql
 AND :campo_fecha >= :'desde' AND :campo_fecha < :'hasta'
) AS endpoint \gdesc
\echo '@@FILAS@@'
SELECT row_to_json(endpoint)::text FROM (
:base_sql
 AND :campo_fecha >= :'desde' AND :campo_fecha < :'hasta'
) AS endpoint;

-- 4. Resumen (stderr) ------------------------------------------------------
SELECT count(*) AS filas FROM (
:base_sql
 AND :campo_fecha >= :'desde' AND :campo_fecha < :'hasta'
) AS endpoint \gset
\warn 'filas exportadas: ' :filas
