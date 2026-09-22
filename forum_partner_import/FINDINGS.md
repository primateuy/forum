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

---

# Hallazgo: dos copias de `aml_secondary_currency`, y gana la vieja

> Documento de insumo. **No se aplicó ningún cambio**: es deuda del repo, a
> sanear con decisión de equipo. Relevado el 2026-09-17 sobre `o17_support_forum`
> y su copia `o17_inv_med`, mientras se medía el apply del ajuste de inventario.

## Qué se encontró

El módulo técnico `aml_secondary_currency` existe **dos veces** en el
`addons_path` de `forum.conf`, con el mismo nombre de carpeta:

| copia | posición en `addons_path` |
|---|---|
| `_shared/general_primate/aml_secondary_currency/` | **12** |
| `forum/aml_secondary_currency/` | **33** |

Odoo resuelve un módulo por la primera carpeta que lo encuentra, así que **corre
la de `general_primate`**. Tres pruebas independientes:

1. el orden del `addons_path` en `forum.conf`;
2. `general_primate/.../models/__pycache__/` tiene los `.pyc` compilados y
   `forum/aml_secondary_currency` **no tiene `__pycache__`**: el server nunca la
   importó;
3. el código de las dos difiere.

Es el mismo patrón de shadowing ya documentado en `CLAUDE.md` para
`POScybrosys` contra `CybroAddons`.

## Por qué importa

Las dos copias se comportan **distinto ante la falta de cotización**, y la que
corre es la más estricta:

- **`general_primate` (la que corre):** busca la cotización con
  `('name', '=', fecha)` —**fecha exacta, sin fallback**— y **levanta
  `UserError`** («No se encontró tipo de cambio para la fecha … y moneda …»)
  desde `compute_amount_secondary()`, que su propio `_post()` invoca sobre las
  líneas de todo asiento que quede `posted`.
- **`forum/` (la que NO corre):** tiene el commit `55125f5`
  *[FIX][4827] Divisa secundaria no frena la facturación*, que cambia el
  criterio a «última cotización ≤ fecha» y a no interrumpir (deja
  `amount_secondary` en 0 y sólo loguea).

O sea: **hay un fix hecho y probado que no tiene ningún efecto**, y quien lea
`forum/aml_secondary_currency` va a concluir que el problema está resuelto. Pasó
en esta misma sesión: se leyó la copia equivocada y se dio por bueno que la
divisa secundaria no podía frenar una publicación masiva de asientos.

## Consecuencia práctica para este módulo

Las 6 compañías tienen `secondary_currency_id` (USD), así que **para publicar
cualquier asiento tiene que existir una fila en `res_currency_rate` de esa
moneda con la fecha contable EXACTA del asiento**. Por eso la fase de
publicación valida la cotización antes de arrancar (ver el README) en lugar de
fallar a mitad de tanda.

## Opciones para sanearlo (no se hizo)

1. Borrar `_shared/general_primate/aml_secondary_currency/` y quedarse con la de
   `forum/`, que tiene el fix. Afecta a **todos** los clientes que carguen
   `general_primate`: hay que revisar uno por uno.
2. Reordenar el `addons_path` de `forum.conf` para que `forum/` gane. Cambia la
   resolución de **cualquier** otro módulo duplicado: más barato de escribir y
   más difícil de predecir.
3. Portar el fix a la copia de `general_primate` y dejar la de `forum/` como
   está. Es lo menos invasivo, pero deja las dos copias vivas.

La 1 es la correcta a largo plazo; la 3, la de menor riesgo inmediato.

## Defecto propio: el invariante 5c era inviable a escala (corregido)

La primera versión del control de **huecos en la numeración** del diario usaba una
ventana:

```sql
SELECT sequence_number - lag(sequence_number) OVER (
           PARTITION BY sequence_prefix ORDER BY sequence_number)
  FROM account_move WHERE state = 'posted' AND (sequence_prefix, sequence_number) IN (...)
```

y dentro de ese `IN` acotaba el rango del ajuste con **dos subconsultas
correlacionadas** por `am.sequence_prefix` (el `min` y el `max`). Correlacionadas
significa que se reevalúan por fila candidata, y la ventana recorría
`account_move` entera.

**Medido sobre la base del peor caso (829.000 asientos): más de 1 h 40 min en ese
único control, con 161 MB de temporales en disco y sin haber terminado.** La fase
de verificación completa habría costado más que la publicación entera (3 h 29 min),
que es tanto como no tenerla: nadie la corre en producción.

**Por qué era innecesario.** Para detectar huecos no hace falta comparar cada
número con el anterior. Si en el rango no falta ninguno, entonces
`count(distinct sequence_number) = max - min + 1`. Son dos agregados que se
apoyan en `account_move_sequence_index`, que **ya existe en el core**
(`journal_id, sequence_prefix DESC, sequence_number DESC, name`). El rango del
ajuste se resuelve **una sola vez** en un CTE en vez de por fila.

Se conservan las dos propiedades que el control tenía que tener: mira **todo el
diario dentro del rango** (los asientos ajenos intercalados no son huecos) y
**acota al rango del ajuste** por prefijo (no reporta huecos anteriores).

Cambia la unidad del contador —el viejo contaba *saltos*, el nuevo cuenta
*prefijos con huecos*— y en los dos el valor esperado es **0**.

## Defecto propio: la paridad comparaba estados distintos del ciclo de vida

El cliente abrió los asientos del ajuste en support —en borrador a propósito,
porque la fase 3 no se corrió— y los vio **todos en `0,00 $`**. Las líneas
estaban bien; lo que estaba vacío era la cabecera: `amount_total` y sus ocho
hermanos son **calculados-almacenados**, el `INSERT` crudo no los computa y
quedan en `NULL`, que Odoo dibuja como cero. Publicar los recalcula, así que el
hueco **sólo existe mientras el asiento está en borrador**.

**Por qué la paridad no lo vio, que es lo que importa.** El arnés normalizaba el
**estado** del asiento, con este argumento —textual del README de entonces—:

> el **estado** del asiento, porque el ORM publica dentro de
> `_validate_accounting_entries` mientras el SQL los deja en borrador a propósito

Suena razonable y es exactamente el error: al normalizar el estado se estaba
comparando **borrador contra publicado**, y eso **deja sin cobertura todo lo que
llena la transición**. No es que faltara un campo en la lista de comparación:
faltaba un estado entero del ciclo de vida. Los nueve campos de importe estaban
en NULL de un lado y llenos del otro, y el diff daba **0 diferencias**.

### La lección, que generaliza

**Una prueba de paridad tiene que comparar el MISMO punto del ciclo de vida.**
Si los dos caminos terminan en estados distintos, no se normaliza la diferencia:
se **frena al que va más lejos** y se compara en cada estado por separado.
Normalizar un estado es decidir no mirar todo lo que ese estado cambia, y eso no
se nota — el diff sigue dando verde.

Es la misma forma que la del invariante caro de abajo: **una verificación que da
«0» no prueba nada si la condición que tenía que ver está fuera de su alcance.**
Allá el control era más caro que lo verificado y nadie lo corría; acá el control
corría y miraba el lado equivocado.

El arnés vive ahora en el repo (`forum/tools/paridad_inventario/`) y compara
**borrador contra borrador** y **publicado contra publicado**, frenando el
`_post` de la gemela ORM para el primero. La primera corrida en modo borrador
encontró, además de los nueve importes ya corregidos, **17 campos de cabecera y
16 de línea** que el ORM llena y la réplica dejaba en NULL.

### La lección de método, que es la que importa
El defecto no lo encontró ninguna prueba: lo encontró **mirar el proceso mientras
corría**. Y estuvo a punto de no encontrarse, porque un proceso trabado en una
consulta pesada se ve **idéntico** a uno colgado: 0 % de CPU y ni una línea de
log. En una corrida anterior se mató por eso, perdiendo el informe. La forma de
distinguirlos es preguntarle a la base, no mirar el proceso:

```sql
SELECT pid, state, wait_event_type, wait_event, now() - query_start AS hace
  FROM pg_stat_activity WHERE datname = '<base>';
```

Dos trampas de esa vista, verificadas: **matar el cliente no cancela la consulta**
(sigue corriendo y compitiendo; hace falta `pg_cancel_backend(pid)`), y **el texto
de `query` viene truncado y alineado** en `track_activity_query_size`
(`length(query) = 1023` en todas las filas), así que un patrón anclado al
principio como `btrim(query) LIKE 'explain%'` **da falso hasta en las filas que sí
son esa consulta**. Filtrar por `%...%` o por pid.

### Verificado fabricando el defecto, y los dos criterios NO son equivalentes

El 5c nuevo se probó **fabricando las violaciones**, no comprobando que diga «0»
sobre datos sanos: dos controles que miran una base sin huecos dicen los dos «0»
aunque uno esté roto y no mire nada. Sobre tres prefijos de juguete —uno sano
(1..10), uno al que le faltan el 5 y el 8, y uno con el 7 duplicado—:

| criterio | `SANO` | `ROTO` | `DUPL` |
|---|---|---|---|
| **5c nuevo** (agregados) | — | **detecta, faltan 2** | — |
| 5c viejo (ventana `lag`) | — | detecta, 2 saltos | **detecta, 1 salto** |
| 5b (duplicados) | — | — | **detecta el 7** |

O sea: el 5c **viejo mezclaba huecos con duplicados**. Dos filas con el mismo
número producen un salto de 0, que no es `1`, y el control lo contaba como hueco
—duplicando el reporte de algo que el **5b** ya controla por separado—. El nuevo
separa las dos cosas: 5b duplicados, 5c faltantes.

**Consecuencia:** los dos criterios no dan el mismo número fila por fila, y el
esperado sigue siendo **0 en ambos** sobre un diario correlativo sano. El nuevo es
el correcto, no sólo el rápido.

Como efecto colateral útil, el nuevo informa **cuántos números faltan** por
prefijo (`esperados - presentes`), que es más accionable que una cuenta de saltos.

## Defecto propio: el apply exigía fila de `ir_property` por categoría (corregido en 17.0.1.3.2)

Síntoma, en la corrida del 2026-09-21 sobre el dump nuevo:

```
ERROR en la tanda de aplicación que arranca en 0: 6 capas de valuación no tienen
cuenta o diario en la categoría de su producto (ejemplos de producto: 1206680,
1206683, 1206687, ...)
```

**No faltaba configuración.** Odoo resuelve una propiedad company-dependent en
**dos niveles** (`base/models/ir_property.py:278`, `_get_multi`):

```sql
WHERE p.fields_id = %s
  AND (p.company_id = %s OR p.company_id IS NULL)
  AND (p.res_id IN %s OR p.res_id IS NULL)   -- <- el default de la compañía
ORDER BY p.company_id NULLS FIRST
```

La fila con `res_id IS NULL` es el **valor por defecto para todas las
categorías**. `_apl_asientos` exigía fila explícita por categoría, así que una
categoría que se apoya en el default daba `NULL` y cortaba la tanda — aunque el
producto valúe perfecto en Odoo.

En `o17_inv_med` los defaults existen para las 6 compañías (valuación
`account.account,74`, salida `194`, diario `account.journal,15`) y **15
categorías de la compañía 1 marcadas `real_time` no tienen ninguna fila propia**.
Ahí no explotó porque ninguna de esas 15 tiene un solo producto almacenable con
stock; en el dump nuevo sí los hay.

El patrón correcto ya estaba **en este mismo archivo** para `property_cost_method`,
`property_stock_inventory` y `standard_price`, con su comentario *«la propiedad
propia y, si no tiene, el default de la compañía. Es el mismo orden que resuelve
el ORM»*. Faltó en la consulta de cuentas y en el invariante 4d.

`property_valuation` tenía el mismo hueco pero **en silencio**: una categoría con
default `real_time` y sin fila propia se trataba como `manual`, y el módulo no
creaba el asiento que el ORM sí crea. Peor que el error, porque no avisa.

### Dos detalles que no son obvios

**La precedencia va por presencia de fila, no por valor.** Una fila explícita con
el valor vacío gana igual y deja la cuenta en NULL — que es exactamente lo que
hace el ORM (devuelve `False` y corta con `UserError`). Un `coalesce` de valores
taparía ese caso con el default y crearía el asiento que el ORM se niega a crear.
Por eso la resolución es un `ORDER BY (res_id IS NULL), (company_id IS NULL)
LIMIT 1` y no un `coalesce`.

**Se filtra por `fields_id`, no por `ir_property.name`.** En el nivel del default
no hay `res_id` que desempate, y el nombre solo no distingue la propiedad de otro
modelo.

## Defecto propio: `acc_src` y `acc_dest` eran la misma cuenta (corregido en 17.0.1.3.2)

Aparecido al revisar lo anterior. El core saca las dos contrapartidas de **puntas
distintas del movimiento** (`stock_account/models/stock_move.py:392`):

```python
def _get_src_account(self, accounts_data):
    return self.location_id.valuation_out_account_id.id or accounts_data['stock_input'].id

def _get_dest_account(self, accounts_data):
    if not self.location_dest_id.usage in ('production', 'inventory'):
        return accounts_data['stock_output'].id
    return self.location_dest_id.valuation_in_account_id.id or accounts_data['stock_output'].id
```

En una **entrada** la ubicación de ajuste es el ORIGEN, y la cuenta que manda es
`valuation_out_account_id` con respaldo en la cuenta de **entrada** de la
categoría. En una **salida** es el DESTINO, y manda `valuation_in_account_id` con
respaldo en la de **salida**. El módulo usaba `valuation_in_account_id` y la
cuenta de salida **en las dos direcciones**.

**Por qué la paridad no lo había visto.** En esta base la cuenta de entrada y la
de salida son la misma (`account.account,194`) en las 101 categorías que las
tienen y también en el default, y **ninguna ubicación tiene cuentas de valuación
propias**. Con esos datos las dos fórmulas dan idéntico y el diff da 0.

Se destapó fabricando la diferencia: cuentas distintas para entrada y salida en
una categoría, y cuentas de valuación en la ubicación de ajuste. Sobre 40
movimientos reales de `o17_inv_med`, contra
`_get_accounting_data_for_valuation()` del ORM:

| contrapartida | fórmula nueva | fórmula vieja |
|---|---|---|
| entrada | 20 bien / 0 mal | **0 bien / 20 mal** |
| salida  | 20 bien / 0 mal | 20 bien / 0 mal |

El ORM valida `acc_src` **y** `acc_dest` antes de saber la dirección, así que el
chequeo de configuración ahora exige las dos, más valuación y diario.

### El `MATERIALIZED` del invariante 4d no es decorativo

Al resolver las propiedades en un CTE, Postgres lo **inlinea** (PG ≥ 12 con una
sola referencia) y ejecuta las subconsultas como `SubPlan` dentro del `Join
Filter`: una vez por cada una de las 1,6 M de líneas. Medido sobre el batch 11:
**21,9 s sin materializar contra 1,6 s con**. La fase entera de invariantes pasa
de 25 s a 8,5 s.

Y el control se probó **fabricando el defecto**, no viendo que diga «0». Con una
categoría apoyada en el default y **una** línea con la cuenta cambiada:

| | 4d viejo | 4d nuevo |
|---|---|---|
| base sana | 0 | 0 |
| categoría apoyada en el default | 0 | 0 |
| + una línea con otra cuenta | **0 (ciego)** | **1** |

El viejo era ciego porque con las propiedades en NULL, `account_id NOT IN (NULL,
NULL)` da NULL y la fila no se cuenta. De ahí el `IS DISTINCT FROM`.

## Defecto propio: la fase 4 se probó sobre un fixture viejo y el rojo era del fixture

La primera corrida completa de la conciliación fue así: **77 grupos procesados,
0 errores, 2,3 s**, y el invariante pasó de **77 violaciones a 76**. Con la fase
corriendo limpia. Lo que tardó fue entender que el defecto no estaba en la fase.

`reconcile()` trabaja sobre `amount_residual`, y en esa base el residual valía
**cero en las 828.781 líneas**. `reconcile()` sobre residual cero **no hace nada
y no levanta nada**: procesa el grupo, no compensa, y devuelve control como si
hubiera funcionado.

El residual estaba en cero porque los datos se habían aplicado el **18-09** con
el motor anterior a `e34d99d`, que es el commit —**del mismo día de la prueba**—
que agregó `amount_residual` al recompute por ORM. El fixture era de una versión
anterior a la corrección que la prueba necesitaba.

Recalculando el residual como lo hace el motor actual, la misma fase sobre los
mismos 77 grupos deja el invariante en **0**.

**La lección de método:** una base de pruebas con datos ya aplicados es un
fixture con versión, y su versión es la del motor que los generó. Antes de leer
un resultado sobre datos viejos hay que preguntarse qué commits entraron después
de que se generaron. El síntoma —una fase que corre sin error y no logra nada—
es idéntico al de un defecto propio.

### Y de paso, la trampa de fondo

`amount_residual` es un calculado-almacenado cuyo `@api.depends`
(`account_move_line.py:749`) **no incluye `move_id.state`**: se calcula al crear
la línea y **publicar no lo recalcula**. Cualquier camino que inserte líneas sin
pasar por el `create()` del ORM tiene que completarlo, o la conciliación queda
muda. Vale para el motor (está en `_CAMPOS_POR_ORM`) y para el `.sql` de
reparación de los borradores ya instalados.

## Defecto propio: el autor de lo que escribe `reconcile()` lo elegía otro

El arnés marcó `write_uid` sql=1 contra orm=2 en las líneas conciliadas. La
primera hipótesis —el `sudo()` de la fase— era falsa: **desde la 13 `sudo()`
sólo levanta el flag de superusuario y no cambia el `uid`**, y de hecho la fase 3
publica con `.sudo()` y deja `write_uid = 2` en los 1.657.562 renglones de la
corrida real.

Lo que pasa es otra cosa. `reconcile()` deja `matching_number` y
`full_reconcile_id` sucios en la caché, y quien los baja a la base es **el primer
flush que pase**. El propio `cr.savepoint()` llama a `Transaction.flush()` al
salir, y ese método elige **un entorno cualquiera de la transacción** —el primero
con `uid`—, que puede ser el de otro. En producción no se notaba porque la fase 3
commitea antes de llegar a la 4; en el arnés las dos fases van en la misma
transacción y ahí quedó a la vista.

La corrección: **flushear adentro del savepoint y con el entorno del proceso**.
Así el autor de las filas no depende de quién más esté en la transacción. Y de
paso resuelve algo que no es cosmético: `_rec_grupos_sql` lee `reconciled` y
`state` por **SQL crudo**, así que si el ORM tiene escrituras pendientes la
consulta elige mal los grupos. Todo camino que lea por SQL crudo después de
escribir por ORM tiene que flushear primero.
