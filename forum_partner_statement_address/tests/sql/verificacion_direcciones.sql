-- Verificacion independiente del agrupamiento por direccion.
--
-- Reparte el saldo pendiente a cobrar de un partner comercial entre sus
-- direcciones usando la MISMA expresion que el reporte, pero calculando el
-- abierto con `amount_residual` de Odoo en vez de con las consultas de OCA.
-- Sirve como contraste: si el reporte y esto dan distinto, el reporte miente.
--
-- Uso:
--   psql -d <BASE> -f verificacion_direcciones.sql
-- Editar el CTE `parametros` para apuntar a otro cliente, fecha o compania.

WITH parametros AS (
    SELECT 1::int                                AS company_id,
           DATE '2026-12-31'                     AS fecha,
           'POC-DIR FRANQUICIAS DEMO S.A.'::text AS partner,
           -- 'invoice' = direccion de facturacion, 'delivery' = de entrega
           'invoice'::text                       AS modo
),
comercial AS (
    SELECT p.id
    FROM res_partner p, parametros x
    WHERE p.name = x.partner AND p.parent_id IS NULL
),
-- res_partner no tiene parent_path en esta base: se baja por parent_id.
direcciones AS (
    WITH RECURSIVE arbol AS (
        SELECT p.id, p.name FROM res_partner p JOIN comercial c ON c.id = p.id
        UNION ALL
        SELECT h.id, h.name FROM res_partner h JOIN arbol a ON h.parent_id = a.id
    )
    SELECT id, name FROM arbol
),
apuntes AS (
    SELECT CASE
               WHEN x.modo = 'delivery' THEN
                   CASE WHEN COALESCE(m.forum_shipping_partner_id,
                                      m.partner_shipping_id,
                                      m.partner_id) IN (SELECT id FROM direcciones)
                        THEN COALESCE(m.forum_shipping_partner_id,
                                      m.partner_shipping_id,
                                      m.partner_id)
                        ELSE l.partner_id END
               ELSE
                   CASE WHEN COALESCE(m.forum_address_partner_id,
                                      m.partner_id) IN (SELECT id FROM direcciones)
                        THEN COALESCE(m.forum_address_partner_id, m.partner_id)
                        ELSE l.partner_id END
           END                              AS direccion_id,
           l.amount_residual                AS abierto
    FROM account_move_line l
    JOIN account_move m     ON m.id = l.move_id
    JOIN account_account aa ON aa.id = l.account_id
    CROSS JOIN parametros x
    WHERE l.partner_id IN (SELECT id FROM comercial)
      AND aa.account_type = 'asset_receivable'
      AND m.state = 'posted'
      AND l.company_id = x.company_id
      AND l.date <= x.fecha
      AND NOT l.blocked
)
SELECT CASE WHEN GROUPING(d.name) = 1 THEN '>>> SUMA POR DIRECCION'
            WHEN d.name IS NULL       THEN '(direccion fuera del grupo)'
            ELSE d.name END                       AS hoja,
       count(*)                                   AS apuntes,
       round(sum(a.abierto)::numeric, 2)          AS pendiente
FROM apuntes a
LEFT JOIN direcciones d ON d.id = a.direccion_id
GROUP BY ROLLUP (d.name)
ORDER BY GROUPING(d.name), d.name;

-- La fila '>>> SUMA POR DIRECCION' tiene que coincidir exactamente con el
-- pendiente del partner comercial calculado sin agrupar:
WITH parametros AS (
    SELECT 1::int AS company_id, DATE '2026-12-31' AS fecha,
           'POC-DIR FRANQUICIAS DEMO S.A.'::text AS partner
),
comercial AS (
    SELECT p.id FROM res_partner p, parametros x
    WHERE p.name = x.partner AND p.parent_id IS NULL
)
SELECT 'TOTAL NATIVO DEL PARTNER COMERCIAL'      AS control,
       round(sum(l.amount_residual)::numeric, 2) AS pendiente
FROM account_move_line l
JOIN account_move m     ON m.id = l.move_id
JOIN account_account aa ON aa.id = l.account_id
CROSS JOIN parametros x
WHERE l.partner_id IN (SELECT id FROM comercial)
  AND aa.account_type = 'asset_receivable'
  AND m.state = 'posted'
  AND l.company_id = x.company_id
  AND l.date <= x.fecha
  AND NOT l.blocked;
