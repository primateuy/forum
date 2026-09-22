-- ===================================================================
-- Reparación de los asientos EN BORRADOR del ajuste de inventario
--
-- Qué arregla, sobre asientos ya creados por una versión anterior del
-- módulo (<= 17.0.1.3.2):
--   1. Los nueve importes de la cabecera, que quedaron en NULL y por eso
--      la lista mostraba todo en 0,00 $.
--   2. El resto de campos calculados-almacenados de cabecera y línea.
--   3. La referencia, al formato legible con código, atributos y sucursal.
--   4. El residual de la LÍNEA, que quedó en cero y sin el cual la
--      conciliación (fase 4) no tiene con qué trabajar.
--
-- Qué NO toca:
--   * Asientos PUBLICADOS: al publicar, el ORM ya completó todo. Esta
--     reparación es sólo para los que están esperando revisión.
--   * Asientos que no sean de nuestro ajuste (ver la identificación).
--   * El debe y el haber de las líneas: siempre estuvieron bien. Acá no
--     se toca ni uno.
--   * Las conciliaciones ya existentes: las líneas que tengan una
--     conciliación parcial se saltean y se informan aparte.
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
-- 5. Residual de la LÍNEA.
--    `amount_residual` es un calculado-almacenado cuyo `@api.depends` NO
--    incluye `move_id.state`: se calcula al CREAR la línea y publicar no
--    lo vuelve a tocar (account_move_line.py::_compute_amount_residual).
--    Las líneas creadas por SQL con una versión anterior del módulo
--    quedaron con residual cero, y `reconcile()` sobre un residual cero
--    no hace nada: la conciliación correría sin error y sin efecto.
--
--    Réplica del compute para líneas SIN conciliación parcial (que es el
--    caso acá: son asientos en borrador, nunca se conciliaron):
--      necesita residual = cuenta conciliable, o de tipo efectivo/tarjeta
--      residual          = redondeo(balance) en moneda de la compañía
--      residual_moneda   = redondeo(amount_currency) en la de la línea
--      reconciled        = los dos residuales en cero
-- -------------------------------------------------------------------
UPDATE account_move_line l SET
       amount_residual          = v.residual,
       amount_residual_currency = v.residual_moneda,
       reconciled               = v.conciliada
  FROM (SELECT l2.id,
               CASE WHEN r.necesita
                    THEN round(l2.balance::numeric, cc.decimal_places)
                    ELSE 0 END AS residual,
               CASE WHEN r.necesita
                    THEN round(l2.amount_currency::numeric, lc.decimal_places)
                    ELSE 0 END AS residual_moneda,
               r.necesita
                 AND round(l2.balance::numeric, cc.decimal_places) = 0
                 AND round(l2.amount_currency::numeric, lc.decimal_places) = 0
                 AS conciliada
          FROM account_move_line l2
          JOIN reparar_objetivo o ON o.move_id = l2.move_id
          JOIN account_account ac ON ac.id = l2.account_id
          JOIN res_currency cc ON cc.id = l2.company_currency_id
          JOIN res_currency lc ON lc.id = coalesce(l2.currency_id,
                                                   l2.company_currency_id)
          CROSS JOIN LATERAL (
               SELECT ac.reconcile
                   OR ac.account_type IN ('asset_cash', 'liability_credit_card')
                   AS necesita) r
         -- Nunca pisar una conciliación real.
         WHERE NOT EXISTS (SELECT 1 FROM account_partial_reconcile p
                            WHERE p.debit_move_id = l2.id
                               OR p.credit_move_id = l2.id)) v
 WHERE l.id = v.id
   -- Sólo lo que cambia: una segunda corrida no reescribe nada.
   AND (l.amount_residual          IS DISTINCT FROM v.residual
     OR l.amount_residual_currency IS DISTINCT FROM v.residual_moneda
     OR l.reconciled               IS DISTINCT FROM v.conciliada);

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

-- El residual tiene que ser el saldo en las cuentas conciliables.
SELECT count(*) AS lineas_conciliables_sin_residual_debe_ser_0
  FROM account_move_line l
  JOIN reparar_objetivo o ON o.move_id = l.move_id
  JOIN account_account ac ON ac.id = l.account_id AND ac.reconcile
 WHERE l.balance <> 0
   AND round(l.amount_residual::numeric, 2) IS DISTINCT FROM round(l.balance::numeric, 2);

-- Líquidas salteadas por tener una conciliación de verdad (informativo).
SELECT count(*) AS lineas_salteadas_por_conciliacion_existente
  FROM account_move_line l
  JOIN reparar_objetivo o ON o.move_id = l.move_id
 WHERE EXISTS (SELECT 1 FROM account_partial_reconcile p
                WHERE p.debit_move_id = l.id OR p.credit_move_id = l.id);

\echo 'Revisá los números de arriba. Si todo está en 0, COMMIT; si no, ROLLBACK.'
-- COMMIT;
