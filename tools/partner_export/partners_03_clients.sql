-- Clientes de Forum con la misma salida que la consulta guardada 03_clients
-- (odoo_api_query), para la carga inicial de Heinwiss. SÓLO LECTURA.
--
-- Una única sesión psql, y sólo tres consultas:
--   1. que exista api_query_definition y que el SQL guardado de 03_clients sea
--      el de producción del 01-10-2026 (si difiere, lo muestra y corta);
--   2. max(write_date) y max(create_date) de res_partner: la fecha de corte;
--   3. la exportación (COPY ... TO STDOUT).
--
-- La exportación es el SQL de 03_clients con estos cambios y ningún otro:
--   - sin el filtro de fecha fija (rp.write_date > '2026-03-01');
--   - sin LIMIT/OFFSET;
--   - las tres fechas que la API devuelve crudas (client_sync_local_date,
--     client_updated_date, client_register_date) se escriben como las serializa
--     la API, `datetime.isoformat()`: con `T`, microsegundos sólo si no son 0, y
--     el huso `+00:00` en la que tiene zona.
--
-- Todo lo informativo sale por stderr con \warn; stdout lleva SÓLO el CSV, así
-- se puede redirigir a un archivo local sin que quede nada en el servidor.
-- (No se usa `\o /dev/stderr`: corriendo psql como postgres vía sudo no puede
-- abrir el stderr del usuario que se conectó.) Requiere psql 13+. Uso en README.md.

\set ON_ERROR_STOP 1
SET default_transaction_read_only = on;
SET statement_timeout = '5min';


-- 1. La consulta guardada --------------------------------------------------
SELECT to_regclass('public.api_query_definition') IS NOT NULL AS existe_tabla \gset
\if :existe_tabla
\else
  \warn 'ERROR: no existe api_query_definition en esta base. No se exporta.'
  SELECT 1/0 AS no_existe_api_query_definition;
\endif

-- Se compara con los espacios (y saltos de línea) colapsados y recortados: el texto es el que imprime el log del
-- controlador (sql_query.strip() + LIMIT/OFFSET), sin el LIMIT/OFFSET.
SELECT btrim(regexp_replace(sql_query, '\s+', ' ', 'g')) = btrim(regexp_replace($q03$
SELECT temp.*

FROM (

SELECT

rp.id AS client_id,
rp.name AS client_name, -- 3-2
TO_CHAR(rp.birthdate_date::timestamptz, 'YYYY-MM-DD HH24:MI:SS.MS')   AS client_dob,  -- 3-3

CASE rp.gender
  WHEN 'F' THEN 'Femenino'
  WHEN 'M' THEN 'Masculino'
  ELSE 'Sin definir'
END AS client_gender,

rp.phone_sanitized AS client_phone, --3.5
rp.city AS client_city, -- 3-6
rp.email AS client_mail, -- 3-7

CASE
        WHEN email_normalized IS NULL THEN 'EMPTY'
        ELSE 'VALID'
END AS client_mail_is_good,  -- 3-8

now() AS  client_sync_local_date,  -- 3-9
rp.write_date AS client_updated_date, -- 3-10
rp.create_date AS client_register_date, -- 3-11

CASE WHEN rp.is_company THEN 'Empresa' ELSE 'Persona' END AS client_category,  -- 3-12
CASE WHEN rp.is_company  THEN '0' ELSE '1' END AS client_is_b2c, -- 3-13

rp.ref AS  client_id_card, -- 3-14

'' AS client_first_branch_id,  --3-15
''  AS  client_last_branch_id,   --3-16
''  AS  client_first_branch,   --3-17
''  AS client_last_branch    --3-18


FROM public.res_partner rp

WHERE
  1 = 1
  AND customer_rank > 0
  AND
rp.write_date > '2026-03-01'

) as temp

WHERE 1=1
$q03$, '\s+', ' ', 'g')) AS consulta_igual
  FROM api_query_definition WHERE query_key = '03_clients' \gset
\if :consulta_igual
  \warn 'OK: la consulta 03_clients guardada es la esperada.'
\else
  \warn 'ERROR: la consulta 03_clients guardada DIFIERE de la esperada. No se exporta. Guardada:'
  SELECT sql_query AS guardada FROM api_query_definition WHERE query_key = '03_clients' \gset
  \warn :guardada
  SELECT 1/0 AS consulta_03_clients_difiere;
\endif

-- 2. Fecha de corte ---------------------------------------------------------
SELECT max(write_date) AS max_write_date, max(create_date) AS max_create_date
  FROM res_partner \gset
\warn 'Fecha de corte: max(write_date) =' :max_write_date '| max(create_date) =' :max_create_date

-- 3. Exportación -------------------------------------------------------------
COPY (
SELECT temp.*

FROM (

SELECT

rp.id AS client_id,
rp.name AS client_name, -- 3-2
TO_CHAR(rp.birthdate_date::timestamptz, 'YYYY-MM-DD HH24:MI:SS.MS')   AS client_dob,  -- 3-3

CASE rp.gender
  WHEN 'F' THEN 'Femenino'
  WHEN 'M' THEN 'Masculino'
  ELSE 'Sin definir'
END AS client_gender,

rp.phone_sanitized AS client_phone, --3.5
rp.city AS client_city, -- 3-6
rp.email AS client_mail, -- 3-7

CASE
        WHEN email_normalized IS NULL THEN 'EMPTY'
        ELSE 'VALID'
END AS client_mail_is_good,  -- 3-8

-- isoformat() de un timestamptz: la API lo recibe en la zona de la sesión
-- (la del servidor) con su desplazamiento, p. ej. 2026-10-01T14:39:00.123456+00:00
TO_CHAR(now(), 'YYYY-MM-DD"T"HH24:MI:SS')
  || CASE WHEN TO_CHAR(now(), 'US') <> '000000' THEN '.' || TO_CHAR(now(), 'US') ELSE '' END
  || TO_CHAR(now(), 'TZH:TZM') AS  client_sync_local_date,  -- 3-9
-- isoformat() de un timestamp sin zona: 2026-09-08T18:51:31.393961
TO_CHAR(rp.write_date, 'YYYY-MM-DD"T"HH24:MI:SS')
  || CASE WHEN TO_CHAR(rp.write_date, 'US') <> '000000' THEN '.' || TO_CHAR(rp.write_date, 'US') ELSE '' END
  AS client_updated_date, -- 3-10
TO_CHAR(rp.create_date, 'YYYY-MM-DD"T"HH24:MI:SS')
  || CASE WHEN TO_CHAR(rp.create_date, 'US') <> '000000' THEN '.' || TO_CHAR(rp.create_date, 'US') ELSE '' END
  AS client_register_date, -- 3-11

CASE WHEN rp.is_company THEN 'Empresa' ELSE 'Persona' END AS client_category,  -- 3-12
CASE WHEN rp.is_company  THEN '0' ELSE '1' END AS client_is_b2c, -- 3-13

rp.ref AS  client_id_card, -- 3-14

'' AS client_first_branch_id,  --3-15
''  AS  client_last_branch_id,   --3-16
''  AS  client_first_branch,   --3-17
''  AS client_last_branch    --3-18


FROM public.res_partner rp

WHERE
  1 = 1
  AND customer_rank > 0

) as temp

WHERE 1=1
) TO STDOUT WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
