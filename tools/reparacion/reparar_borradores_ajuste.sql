-- ===================================================================
-- Reparación de los asientos EN BORRADOR del ajuste de inventario
--
-- Qué arregla, sobre asientos ya creados por una versión anterior del
-- módulo (<= 17.0.1.3.2):
--   1. Los nueve importes de la cabecera, que quedaron en NULL y por eso
--      la lista mostraba todo en 0,00 $.
--   2. El resto de campos calculados-almacenados de cabecera y línea.
--   3. La referencia, al formato legible con código, atributos y sucursal.
--
-- Qué NO toca:
--   * Asientos PUBLICADOS: al publicar, el ORM ya completó todo. Esta
--     reparación es sólo para los que están esperando revisión.
--   * Asientos que no sean de nuestro ajuste (ver la identificación).
--   * Las LÍNEAS contables: sus importes siempre estuvieron bien. Acá no
--     se toca ni un debe ni un haber.
--
-- Es IDEMPOTENTE: correrlo dos veces deja el mismo resultado.
-- Corre entero dentro de una transacción; si algo no cuadra, ROLLBACK.
-- ===================================================================

-- Uso:
--   psql -h <host> -U <user> -d <base> -v BATCH=11 \
--        -f reparar_borradores_ajuste.sql
-- BATCH es el id del batch de inventario (la tabla de staging es
-- forum_import_staging_<BATCH>). Se corre con la revisión a la vista: el
-- script NO hace COMMIT solo.
\set ON_ERROR_STOP on
BEGIN;

-- -------------------------------------------------------------------
-- Identificación SIN AMBIGÜEDAD de nuestros asientos.
--
-- Por `stock_move.origin`, donde el módulo escribe el motivo del batch
-- (`inventory_reason`). Es la única marca propia: `reference` replica el
-- texto de Odoo y lo comparten los ajustes manuales.
--
-- La ventana de fechas NO alcanza: en la misma ventana hay ajustes hechos a
-- mano por gente, y ya nos confundieron una vez al interpretar el invariante
-- 3a bis. Medido: 835.309 movimientos con nuestro origen y 12.629 sin él.
-- Tampoco sirve el staging: puede estar vacío después de la corrida.
DROP TABLE IF EXISTS reparar_objetivo;
CREATE TEMP TABLE reparar_objetivo ON COMMIT DROP AS
SELECT am.id AS move_id, am.stock_move_id, am.company_id, m.product_id,
       CASE WHEN ld.usage = 'internal' THEN m.location_dest_id ELSE m.location_id END
         AS location_id
  FROM account_move am
  JOIN stock_move m ON m.id = am.stock_move_id AND m.is_inventory
  JOIN stock_location ls ON ls.id = m.location_id
  JOIN stock_location ld ON ld.id = m.location_dest_id
  JOIN forum_import_batch b ON b.id = :BATCH
 WHERE am.state = 'draft'
   AND am.move_type = 'entry'
   AND b.inventory_reason IS NOT NULL
   AND m.origin = b.inventory_reason;

CREATE INDEX ON reparar_objetivo (move_id);
ANALYZE reparar_objetivo;

-- -------------------------------------------------------------------
-- CHECK ANTES
-- -------------------------------------------------------------------
\echo '=== ANTES ==='
SELECT count(*) AS asientos_a_reparar FROM reparar_objetivo;

SELECT count(*) FILTER (WHERE am.amount_total IS NULL)        AS cabecera_sin_importe,
       count(*) FILTER (WHERE coalesce(am.amount_total,0) = 0) AS cabecera_en_cero,
       count(*) FILTER (WHERE am.ref NOT LIKE '[%')            AS referencia_vieja
  FROM account_move am JOIN reparar_objetivo o ON o.move_id = am.id;

-- Control de seguridad: ningún asiento publicado dentro del objetivo.
SELECT count(*) AS publicados_en_el_objetivo_debe_ser_0
  FROM account_move am JOIN reparar_objetivo o ON o.move_id = am.id
 WHERE am.state <> 'draft';

-- -------------------------------------------------------------------
-- 1. Importes de la cabecera.
--    Para un asiento misceláneo el core suma SOLO las líneas de débito y
--    `direction_sign` vale 1: de los nueve campos, tres llevan el importe
--    y seis van en cero. (account/models/account_move.py::_compute_amount)
-- -------------------------------------------------------------------
WITH debe AS (
    SELECT l.move_id, round(sum(l.debit)::numeric, cur.decimal_places) AS importe
      FROM account_move_line l
      JOIN reparar_objetivo o ON o.move_id = l.move_id
      JOIN account_move am ON am.id = l.move_id
      JOIN res_company c ON c.id = am.company_id
      JOIN res_currency cur ON cur.id = c.currency_id
     GROUP BY l.move_id, cur.decimal_places
)
UPDATE account_move am SET
       amount_total                    = d.importe,
       amount_total_signed             = d.importe,
       amount_total_in_currency_signed = d.importe,
       amount_untaxed                  = 0,
       amount_tax                      = 0,
       amount_residual                 = 0,
       amount_untaxed_signed           = 0,
       amount_tax_signed               = 0,
       amount_residual_signed          = 0
  FROM debe d
 WHERE am.id = d.move_id
   AND am.amount_total IS DISTINCT FROM d.importe;   -- idempotencia

-- -------------------------------------------------------------------
-- 2. Resto de calculados-almacenados de la CABECERA.
--    `posted_before` va a NULL: el ORM lo deja sin valor y la regla es
--    quedar idénticos, aunque un false y un NULL se lean igual.
-- -------------------------------------------------------------------
UPDATE account_move am SET
       always_tax_exigible           = true,
       depreciation_value            = 0,
       extract_state_processed       = false,
       is_in_extractable_state       = false,
       is_storno                     = false,
       payment_distribution_complete = false,
       payment_state                 = 'not_paid',
       sequence_number               = 0,
       sequence_prefix               = '',
       invoice_date_due              = am.date,
       posted_before                 = NULL
  FROM reparar_objetivo o
 WHERE am.id = o.move_id
   AND (am.always_tax_exigible IS DISTINCT FROM true
     OR am.payment_state IS DISTINCT FROM 'not_paid'
     OR am.sequence_prefix IS DISTINCT FROM ''
     OR am.posted_before IS NOT NULL);

-- -------------------------------------------------------------------
-- 3. Resto de calculados-almacenados de la LÍNEA.
-- -------------------------------------------------------------------
UPDATE account_move_line l SET
       journal_id      = am.journal_id,
       move_name       = am.name,
       account_root_id = ac.root_id,
       price_subtotal  = 0,
       price_total     = 0,
       price_unit      = 0,
       reconciled      = false,
       tax_tag_invert  = false,
       invoice_date    = am.invoice_date
  FROM account_move am, reparar_objetivo o, account_account ac
 WHERE am.id = o.move_id
   AND l.move_id = am.id
   AND ac.id = l.account_id
   AND (l.journal_id IS DISTINCT FROM am.journal_id
     OR l.account_root_id IS DISTINCT FROM ac.root_id
     OR l.move_name IS DISTINCT FROM am.name);

-- -------------------------------------------------------------------
-- 4. Referencia al formato nuevo.
--    [código] plantilla (atributos) · sucursal · motivo, a 120.
--    El display_name se arma acá con los valores de atributo, que es lo
--    que hace el core; el módulo lo lee por ORM, pero en un .sql no hay
--    ORM, así que se replica con el mismo orden de atributos.
-- -------------------------------------------------------------------
DROP TABLE IF EXISTS reparar_nombre;
CREATE TEMP TABLE reparar_nombre ON COMMIT DROP AS
SELECT o.move_id,
       left(
         '[' || coalesce(pp.default_code, '') || '] '
         || coalesce(pt.name ->> 'es_UY', pt.name ->> 'es_419',
                     pt.name ->> 'en_US', '')
         || coalesce(' (' || (
              SELECT string_agg(coalesce(pav.name ->> 'es_UY',
                                         pav.name ->> 'es_419',
                                         pav.name ->> 'en_US'), ', '
                                ORDER BY pav.sequence, ptav.id)
                FROM product_variant_combination pvc
                JOIN product_template_attribute_value ptav
                  ON ptav.id = pvc.product_template_attribute_value_id
                JOIN product_attribute_value pav ON pav.id = ptav.product_attribute_value_id
               WHERE pvc.product_product_id = pp.id) || ')', '')
         || ' · ' || coalesce(w.name, l.complete_name, '')
         || ' · ' || coalesce(am.ref, ''),
       120) AS referencia
  FROM reparar_objetivo o
  JOIN account_move am ON am.id = o.move_id
  JOIN product_product pp ON pp.id = o.product_id
  JOIN product_template pt ON pt.id = pp.product_tmpl_id
  LEFT JOIN stock_location l ON l.id = o.location_id
  LEFT JOIN stock_warehouse w ON w.id = l.warehouse_id
 WHERE am.ref NOT LIKE '[%';   -- idempotencia: sólo las que siguen viejas

UPDATE account_move am SET ref = n.referencia
  FROM reparar_nombre n WHERE am.id = n.move_id;

UPDATE account_move_line l SET name = n.referencia
  FROM reparar_nombre n WHERE l.move_id = n.move_id;

-- -------------------------------------------------------------------
-- CHECK DESPUÉS
-- -------------------------------------------------------------------
\echo '=== DESPUÉS ==='
SELECT count(*) FILTER (WHERE am.amount_total IS NULL)         AS cabecera_sin_importe_debe_ser_0,
       count(*) FILTER (WHERE am.ref NOT LIKE '[%')            AS referencia_vieja_debe_ser_0,
       count(*) FILTER (WHERE length(am.ref) > 120)            AS referencia_larga_debe_ser_0,
       count(*)                                                AS asientos
  FROM account_move am JOIN reparar_objetivo o ON o.move_id = am.id;

-- La cabecera tiene que decir lo mismo que la suma de sus débitos.
SELECT count(*) AS cabecera_distinta_de_sus_lineas_debe_ser_0
  FROM account_move am
  JOIN reparar_objetivo o ON o.move_id = am.id
  JOIN LATERAL (SELECT sum(debit) AS debe FROM account_move_line
                 WHERE move_id = am.id) x ON true
 WHERE round(x.debe::numeric, 2) IS DISTINCT FROM round(am.amount_total::numeric, 2);

-- Cabecera y línea tienen que decir lo mismo.
SELECT count(*) AS referencia_distinta_entre_cabecera_y_linea_debe_ser_0
  FROM account_move am
  JOIN reparar_objetivo o ON o.move_id = am.id
  JOIN account_move_line l ON l.move_id = am.id
 WHERE l.name IS DISTINCT FROM am.ref;

-- Nada publicado tocado.
SELECT count(*) AS publicados_tocados_debe_ser_0
  FROM account_move am JOIN reparar_objetivo o ON o.move_id = am.id
 WHERE am.state <> 'draft';

\echo 'Revisá los números de arriba. Si todo está en 0, COMMIT; si no, ROLLBACK.'
-- COMMIT;
