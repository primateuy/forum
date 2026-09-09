# Hallazgo: claves foráneas sin índice sobre `res_partner`

> Documento de insumo. **No se aplicó ningún cambio**: queda para decidir con
> el cliente. Relevado el 2026-09-08 sobre `o17_support_forum`.

## Qué se encontró

`res_partner` es referenciada por **124 claves foráneas**. De esas, **61 no
tienen índice** en la columna que hace la referencia.

Cuando una columna con FK no está indexada, PostgreSQL tiene que recorrer la
tabla entera cada vez que necesita saber si hay filas apuntando a un contacto
—al borrarlo, y también en cualquier consulta que filtre por esa columna—.

Apareció verificando el procedimiento de reversión de la importación masiva:
el `DELETE` de los contactos creados no terminaba nunca. Pero el impacto va
bastante más allá de la reversión, y esa es la razón de este documento.

## El caso que importa: `loyalty_card.earned_partner_id`

De las 61, una concentra casi todo el problema.

| | |
|---|---|
| Tabla | `loyalty_card` |
| Columna | `earned_partner_id` |
| Filas | **521.875** |
| Definida en | `cambio_precio` (repo `forum`), como *«Ganado por»* |
| Índice | **no tiene** |

**No es un campo muerto: el POS lo consulta.** En
`pos_forum_qz_print/models/pos_order.py` la búsqueda del cupón de próxima
compra filtra por él:

```python
cards = Card.sudo().search([
    ("earned_partner_id", "=", order.partner_id.id),
    ...
])
```

Medido sobre la base real, para una consulta que devuelve **cero** filas:

```
Gather  (actual time=187.846..188.763 rows=0)
  Buffers: shared read=12882
  ->  Parallel Seq Scan on loyalty_card
        Filter: (earned_partner_id = 608819)
```

**188 ms y 12.882 bloques leídos, con dos workers en paralelo, para no
encontrar nada.** Con índice, la misma consulta:

```
Index Scan using ... on loyalty_card  (actual time=0.011..0.011 rows=0)
  Buffers: shared read=3
Execution Time: 0.020 ms
```

**0,020 ms y 3 bloques.** Unas 9.000 veces más rápido, con un índice que ocupa
**3,5 MB**.

Antes de la importación la tabla tenía ~416.000 filas y ya pesaba; ahora tiene
521.875 y va a seguir creciendo con cada cupón emitido, así que el costo de
cada cierre de orden del POS crece con ella.

## Las otras tres con datos

| `loyalty_card` | `earned_partner_id` | 521.875 |
| `account_move` | `partner_shipping_id` | 2.465 |
| `forum_import_batch` | `reference_partner_id` | 5 |
| `procurement_group` | `partner_id` | 2 |

- `account_move.partner_shipping_id`: 2.465 filas. Se nota poco hoy, pero la
  tabla crece con la facturación.
- `forum_import_batch.reference_partner_id`: es del módulo de importación, con
  un puñado de registros. Irrelevante.
- `procurement_group.partner_id`: 2 filas. Irrelevante.

## Las 57 restantes están vacías

Son tablas sin registros en esta base (módulos instalados que no se usan).
No cuestan nada hoy; si alguna empieza a usarse, conviene revisarla.

<details>
<summary>Listado completo</summary>

- `account_analytic_account.partner_id`
- `account_analytic_distribution_model.partner_id`
- `account_analytic_line.partner_id`
- `account_bank_statement_line.partner_id`
- `account_followup_manual_reminder.partner_id`
- `account_move_line_payment_aggregator.partner_id`
- `account_payment.check_partner_id`
- `account_payment.partner_id`
- `account_payment.partner_mps_id`
- `account_payment_register.partner_id`
- `account_reconcile_model_partner_mapping.partner_id`
- `acquirer_liquidation_wizard_voucher.missing_partner_id`
- `advance_reorder_orderprocess.vendor_id`
- `advance_reorder_planner.vendor_id`
- `avatax_validate_address.partner_id`
- `base_partner_merge_automatic_wizard.dst_partner_id`
- `calendar_attendee.partner_id`
- `create_reordering.partner_id`
- `dgi_sucursal.direccion_partner_id`
- `hr_employee.address_id`
- `hr_employee.work_contact_id`
- `hr_work_location.address_id`
- `import_folder_cost.partner_id`
- `logs_res_partner.partner_id`
- `mail_activity.request_partner_id`
- `mail_compose_message.author_id`
- `mps_payment_aggregator.customer_id`
- `mps_payment_aggregator_invoice_selector_wizard.partner_id`
- `partner_cfe_received.partner_id`
- `payment_link_wizard.partner_id`
- `payment_provider.liq_partner_id`
- `payment_token.partner_id`
- `payment_transaction.partner_id`
- `portal_wizard_user.partner_id`
- `pos_config.payment_default_customer_id`
- `product_brand.partner_id`
- `product_purchase_history.partner_id`
- `product_supplierinfo.partner_id`
- `purchase_order.dest_address_id`
- `purchase_order.partner_id`
- `purchase_requisition.vendor_id`
- `purchase_requisition_create_alternative.partner_id`
- `rating_rating.partner_id`
- `rating_rating.rated_partner_id`
- `request_appraisal.author_id`
- `res_company.account_representative_id`
- `res_company.partner_id`
- `setu_intercompany_transfer.fulfiller_partner_id`
- `setu_intercompany_transfer.requestor_partner_id`
- `sms_sms.partner_id`
- `snailmail_letter.partner_id`
- `snailmail_letter_missing_required_fields.partner_id`
- `stock_rule.partner_address_id`
- `stock_scrap.owner_id`
- `stock_warehouse.partner_id`
- `stock_warehouse_orderpoint.partner_id`
- `stock_warehouse_orderpoint.vendor_id`

</details>

## Recomendación

Un solo índice resuelve el 99% del problema:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS loyalty_card_earned_partner_id_idx
    ON loyalty_card (earned_partner_id);
```

`CONCURRENTLY` para no bloquear la tabla mientras se crea (no puede ir dentro
de una transacción). Sobre 521.875 filas tarda pocos segundos.

La forma prolija de dejarlo permanente es en el módulo que define el campo,
`cambio_precio`, agregando `index=True`:

```python
earned_partner_id = fields.Many2one(
    'res.partner', string='Ganado por', readonly=True, index=True,
    help='Cliente que generó este cupón...',
)
```

Así Odoo lo crea y lo mantiene solo, y no depende de que alguien se acuerde de
correr el SQL en cada ambiente. **Ojo:** `cambio_precio` es un módulo del repo
`forum`; el cambio hay que coordinarlo con quien lo mantenga.

El segundo candidato, si en algún momento la facturación pesa, es
`account_move.partner_shipping_id`. El resto no justifica el costo de mantener
un índice.

## Cómo verificarlo en otra base

```sql
SELECT c.conrelid::regclass AS tabla,
       a.attname            AS columna,
       coalesce(s.n_live_tup, 0) AS filas_aprox
  FROM pg_constraint c
  JOIN unnest(c.conkey) k(attnum) ON true
  JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
  LEFT JOIN pg_stat_user_tables s ON s.relid = c.conrelid
 WHERE c.confrelid = 'res_partner'::regclass
   AND c.contype = 'f'
   AND NOT EXISTS (SELECT 1 FROM pg_index i
                    WHERE i.indrelid = c.conrelid
                      AND a.attnum = ANY(i.indkey))
 ORDER BY filas_aprox DESC;
```

Los conteos van a ser distintos en producción: lo que importa es el orden.
