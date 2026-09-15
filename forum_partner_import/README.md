# Importación masiva FORUM: clientes y ajuste de inventario

El batch (`forum.import.batch`) tiene un **Tipo de importación**:

- **Clientes y puntos** — carga ~646.000 clientes y sus puntos de lealtad desde
  un CSV incluido en el módulo, usando SQL directo por tandas para no tumbar el
  servidor. Es todo lo que sigue hasta la sección *Ajuste de inventario*.
- **Ajuste de inventario** — carga el conteo físico de 39 sucursales desde un
  xlsx de doble entrada y lo aplica por tandas. Ver
  [*Ajuste de inventario*](#ajuste-de-inventario) al final.

Los dos comparten la infraestructura: tabla staging UNLOGGED, tandas con commit,
cron que se re-dispara con `_trigger()`, puntero para retomar y el widget de
avance en vivo. Cada tipo engancha en métodos de despacho del modelo base
(`_ruta_relativa_archivo`, `_pasos_de_carga`, `_procesar_tanda`, …) y cae a
`super()` para el resto.

## Por qué SQL y no el ORM

Un `create()` por fila dispara computes, constraints y flush por registro. A
ese ritmo la carga tarda horas y mantiene una transacción abierta enorme. Acá
el CSV entra con `COPY` a una tabla staging y todo el trabajo se hace
set-based, con `commit()` entre tanda y tanda: el servidor sigue respondiendo y
si el proceso se corta retoma desde el puntero.

El ORM se usa solo para el modelo de control, la configuración y la generación
de códigos de tarjeta.

**Medido sobre las 646.073 filas reales (o17_support_forum, 2026-09-08):**

| Etapa | Tiempo |
|---|---|
| `COPY` del CSV (81 MB) | 2,1 s |
| Pre-procesamiento | 36,8 s |
| Procesamiento (128 tandas de 5.000) | 182,4 s |
| **Total** | **~3,7 min**, 0 errores |

## Flujo de uso

1. **Contactos → Importación FORUM → Crear**, con Tipo de importación
   **Clientes y puntos** (es el default).
2. Completar **Partner de referencia** (obligatorio, sin default), **Programa de
   lealtad** y **Tipo de documento**.
3. **1. Cargar staging** — lee el CSV, crea `forum_import_staging_<id>` y
   pre-procesa. Al terminar, el log resume acciones efectivas, discrepancias,
   duplicados resueltos y filas con puntos.
4. Revisar ese resumen. Si algo no cierra, todavía no se tocó nada.
5. **2. Iniciar procesamiento** — genera el backup de tarjetas y activa el
   cron, que avanza en segundo plano. Se puede cerrar la pantalla.
6. Al terminar: `Exportar errores` / `Exportar duplicados` si hace falta, y
   `Borrar staging` cuando ya no se necesite.

Hay además dos botones de reparación, pensados para arreglar corridas viejas.
Los dos son idempotentes y solo tocan lo que está vacío:

- **Reparar campos obligatorios** — completa en toda `res_partner` los
  `Selection` con default que quedaron en `NULL`. Sin esto, el formulario del
  contacto no deja guardar ninguna edición. Ver *Defaults que el ORM habría
  aplicado y el INSERT no*.
- **Completar calle** — vuelca el domicilio del CSV (incluido el literal
  `Sin dirección`) a la calle de los contactos que creó la importación y la
  tienen vacía. Ver *La calle cuando el origen no trae domicilio*.

El cron (`FORUM: importación masiva de clientes`) queda **siempre activo**, con
un intervalo de 10 minutos. El trabajo se dispara con `_trigger()`, que hace
correr un cron activo al instante sin esperar al `nextcall`; el intervalo es
solo la red de seguridad para cuando el servidor se cae con un batch a medias y
se corta la cadena de triggers.

**Por qué no se prende y se apaga solo.** Lo intentaba, y nunca funcionó:
`ir.cron.write()` llama a `_try_lock()`, que pide un lock sobre su propia fila,
y esa fila ya está bloqueada por el cursor que ejecuta el job. Auto-desactivarse
desde adentro del propio cron falla **siempre**:

    psycopg2.errors.LockNotAvailable: could not obtain lock on row in relation "ir_cron"
    UserError: Record cannot be modified right now: This cron task is currently
    being executed and may not be modified

O sea que en la práctica el cron ya quedaba activo para siempre, pero además
tiraba un traceback cada dos minutos. Ahora no hay ningún `write` sobre
`ir.cron` en el módulo: solo `_trigger()`.

## Decisiones tomadas

### Dónde matchea la cédula
En **`res_partner.vat`**, con `l10n_latam_identification_type_id` = **CI**
(id 12 en esta base, configurable en el form). Verificado: 103.545 de los
104.207 contactos usan ese par. El campo custom `numero_doc` de `odoo_fenicio`
está vacío en toda la base — es código muerto y no se usa.

### La columna "En Odoo" del CSV se ignora
La existencia se **re-verifica contra `res_partner`** en el pre-procesamiento,
porque la base pudo cambiar desde que se generó el archivo. En la corrida de
prueba aparecieron **364 discrepancias**: 348 filas marcadas "Actualizar
puntos" cuya cédula no existía (se crean) y 1 marcada "Crear cliente + puntos"
que sí existía (se actualiza, evitando un duplicado). La acción efectiva queda
guardada en `staging.accion_efectiva` para poder auditarla.

### Cédulas duplicadas en la base
Si una cédula aparece en más de un contacto, gana **el que ya tiene tarjeta en
el programa** — así no se le crea una segunda tarjeta a la misma persona a
través de su duplicado. Si ninguno o varios tienen tarjeta, gana el **menor
id**. Cada resolución queda en `staging.dup_motivo` y se exporta con el botón
`Exportar duplicados`.

### Pool de tarjetas
Existen tarjetas del programa ya creadas **sin partner asociado**. El módulo
las consume primero, **de la más vieja a la más nueva** (`id ASC`), tomándolas
con `FOR UPDATE SKIP LOCKED` para que dos procesos concurrentes no se peleen la
misma. El emparejamiento es por posición: `ROW_NUMBER()` sobre las libres
contra `ROW_NUMBER()` sobre las filas pendientes de la tanda.

Cuando el pool se agota — puede pasar **en medio de una tanda**, y está
contemplado — se crean tarjetas nuevas para el resto.

> **Los puntos que traiga una tarjeta del pool se pisan** con los del CSV. Por
> eso el módulo **obliga a hacer un backup** antes de la primera tanda (ver
> abajo). En la base de prueba el pool traía 16,6 millones de puntos de una
> carga anterior de 2025.

### Formato del código de tarjeta
No se imita: se llama al método real `loyalty.card._generate_code()`, que es el
mismo que usa la interfaz al crear una tarjeta a mano:

```python
'044' + str(uuid4())[7:-18]        # -> 044X-XXXX-4XXX, 14 caracteres
```

Los códigos se generan en memoria para toda la tanda, se contrastan contra los
existentes con una sola consulta y las colisiones se regeneran. En la corrida
de prueba: 105.260 tarjetas creadas, **0 códigos duplicados** en toda la tabla,
100% con el patrón correcto.

### Qué se toma del partner de referencia
Lo que el CSV no trae: **`company_id`, `lang`, `tz`, `country_id`** y, si las
tuviera, sus **propiedades por compañía** (`ir_property`, que es donde Odoo 17
guarda los campos company-dependent). Si el partner de referencia usa los
defaults, no se copia nada.

Del CSV salen: `firstname`, `lastname`, `street`, `city`, `state_id`, `phone`,
`mobile`, `email`, `vat`, `birthdate_date` y `gender`.

Fijos: `type='contact'`, `active=true`, `customer_rank=1`, `is_company=false`.

### Campos calculados que el SQL setea a mano
Como el ORM no interviene, el INSERT cubre los *stored computed* de
`res.partner`: `name` (que en esta base **es computado** porque está instalado
`partner_firstname`), `complete_name`, `commercial_partner_id`,
`partner_share`, `email_normalized`, `phone_sanitized` y
`contact_address_complete`. En `loyalty.card`: `company_id` (related stored del
programa).

Verificado forzando al ORM a recalcularlos sobre un registro creado por SQL:
**los 9 campos coinciden exactamente**, todos los constraints pasan y el
`write()` desde la interfaz funciona.

Los ids de `res_partner` y `loyalty_card` se piden por adelantado a la
secuencia (`nextval`) y se guardan en staging. Eso evita depender de
`RETURNING` para correlacionar con el CSV y permite setear
`commercial_partner_id` con el propio id en el mismo INSERT.

### Defaults que el ORM habría aplicado y el INSERT no

Además de los *stored computed*, hay una segunda clase de campo que el INSERT
por SQL se saltea: los `Selection` con `default=` que **no son `required` en
Python pero sí llevan `required="1"` en la vista del core**. Son cuatro:

- `sale_warn` — de `sale`, exigido en `sale/views/res_partner_views.xml:58`
- `purchase_warn` — de `purchase`, en `purchase/views/res_partner_views.xml:105`
- `picking_warn` — de `stock`, en `stock/views/res_partner_views.xml:33`
- `invoice_warn` — de `account`, en `account/views/partner_view.xml:182`

Todos tienen `default='no-message'`. Como no son required a nivel modelo, el
INSERT pasa sin chistar y quedan en `NULL`; después el formulario del contacto
**no deja guardar ninguna edición**, porque la vista los pide y están vacíos.

`_completar_defaults()` los rellena al final de cada tanda. No están listados a
mano: `_campos_required_en_vista()` lee el arch ya heredado del formulario —lo
mismo que recibe el navegador— y se queda con los `required` **incondicionales**
(una expresión como `required="sale_warn and sale_warn != 'no-message'"` depende
de otro campo y no corresponde forzarla). Sobre esos se pide el `default_get()`
al ORM, filtrando a `Selection` stored, no computados, no related, no
company-dependent, y excluyendo `lang`/`tz`. Si mañana otro módulo agrega un
campo con el mismo patrón, entra solo.

**Por qué acotado a la vista y no a todos los `Selection` con default.** En la
base de Forum hay otros dos que el ORM también completaría —
`followup_reminder_type` (recordatorios de cobranza automáticos, Enterprise) y
`vendor_rule` (reabastecimiento, de `setu_advance_reordering`)—. Ninguno de los
dos rompe la edición, y no hay razón para fijar una config de cobranza en
543.000 clientes de retail: quedan como están.

Para las importaciones que ya corrieron sin esto está el botón **"Reparar
campos obligatorios"** (`action_reparar_defaults`), que hace lo mismo sobre
`res_partner` entera. Es idempotente —solo toca lo que está en `NULL`—, va por
tramos de 50.000 ids con commit entre tramo y tramo, y no pisa `write_date`.

### La calle cuando el origen no trae domicilio

El CSV trae el literal `Sin dirección` en **635.056 de las 646.073 filas**
(98,3 %); solo 11.017 tienen una dirección real. La primera versión convertía
ese texto a `NULL`, y el resultado fue que la calle quedaba vacía en casi todas
las fichas.

Ahora ese texto **es el dato**: `_pp_limpieza` normaliza los vacíos y las
variantes de `DOMICILIOS_VACIOS` al valor del campo **Calle cuando no hay dato**
(`street_placeholder`, por defecto `Sin dirección`), y de ahí va a `street` en
el INSERT. Dejar el campo en blanco vuelve al comportamiento viejo.

`contact_address_complete` lo sigue automáticamente, porque `_pp_direcciones` lo
arma desde la misma columna.

Para lo ya importado está el botón **"Completar calle"**
(`action_reparar_direcciones`): renormaliza el staging con el placeholder
vigente y lo vuelca a `street`, recalculando `contact_address_complete` con la
misma fórmula del compute de `web_map`. Dos límites:

- **Solo contactos que creó la importación** (`accion_efectiva = 'crear'`). A
  los que ya existían el módulo no les toca los datos personales, y esto no es
  la excepción.
- **Solo los que tienen la calle vacía**: nunca pisa una dirección real.

Necesita la tabla staging **de la corrida**, porque es lo único que registra qué
contactos creó la importación. Si se recargó el staging después de correr, el
matching marca a todos como `actualizar` y el botón falla con un mensaje
explícito en vez de no hacer nada en silencio.

### Sexo y fecha de nacimiento
`gender` (de `partner_contact_gender`): Femenino→`female`, Masculino→`male`.
**"Desconocido" queda NULL**, porque es ausencia de dato y no un valor
declarado — `other` significaría otra cosa.

`birthdate_date` (de `partner_contact_birthdate`) se parsea con `make_date`,
que **valida** de verdad: un 31/02 queda NULL en vez de correrse al 3 de marzo
como haría `to_date`.

### Qué NO se toca
De los clientes que ya existen **solo se actualizan los puntos**, nunca sus
datos personales. Las filas con `Puntos = 0` no tocan `loyalty` en absoluto.
Las filas con acción `Ya existe - sin puntos` se ignoran enteras.

## Backup obligatorio

Antes de la primera tanda el módulo exporta a CSV `id, code, points,
partner_id, program_id` de todas las tarjetas del programa, a la carpeta que
indique **Carpeta del backup** (default `/tmp`), con timestamp en el nombre:

```
/tmp/loyalty_card_backup_prog2_20260908_184751.csv
```

Si la carpeta no existe, no es escribible, o el archivo queda vacío, **el
procesamiento no arranca**. La ruta queda en el campo `Backup generado` y en el
log.

## Checklist pre-producción

El módulo **no hardcodea ningún conteo**: el pool y los matcheos se consultan en
runtime. Pero antes de correrlo en el destino final hay que hacer esto.

### 1. Dump completo de la base — BLOQUEANTE

**No arrancar el batch sin un dump verificado.** No es una recomendación de
prudencia genérica: **es el único camino de vuelta real.** La reversión completa
por SQL es inviable a este volumen —hay 124 claves foráneas apuntando a
`res_partner`, 61 sin índice, y borrar los ~543.000 contactos creados lleva
alrededor de **8 horas** (ver `FINDINGS.md`)—. Si algo sale mal y no hay dump,
no hay forma práctica de dejar la base como estaba.

```sh
pg_dump -Fc -d <BASE> -f /ruta/backup_pre_import_$(date +%Y%m%d_%H%M%S).dump
```

`-Fc` es formato custom: comprimido y restaurable con `pg_restore` de forma
selectiva. Verificar que terminó bien **antes** de seguir:

```sh
# 1) pg_dump tiene que haber salido con código 0
echo $?

# 2) el archivo no puede estar vacío ni truncado
ls -lh /ruta/backup_pre_import_*.dump

# 3) el índice del dump se tiene que poder leer entero
pg_restore -l /ruta/backup_pre_import_*.dump | tail -5
```

Si `pg_restore -l` falla o corta antes de tiempo, el dump no sirve: rehacerlo.

Para restaurar:

```sh
dropdb <BASE> && createdb <BASE>
pg_restore -d <BASE> -j 4 /ruta/backup_pre_import_XXXXXXXX.dump
```

### 2. Verificaciones sobre la base destino

```sql
-- 2.1) Programa de lealtad a usar y su compañía
SELECT id, name->>'en_US' AS nombre, program_type, active, company_id
  FROM loyalty_program WHERE program_type = 'loyalty' ORDER BY id;

-- 2.2) Pool disponible: ¿alcanza, o hay que crear tarjetas?
--      Comparar contra las filas del CSV con Puntos > 0.
SELECT count(*) FILTER (WHERE partner_id IS NULL) AS libres,
       count(*) FILTER (WHERE partner_id IS NOT NULL) AS asignadas,
       count(*) AS total,
       coalesce(sum(points) FILTER (WHERE partner_id IS NULL), 0) AS puntos_en_el_pool
  FROM loyalty_card WHERE program_id = <PROGRAMA>;

-- 2.3) Tipo de documento de la cédula: confirmar el id antes de cargar
SELECT id, name->>'en_US' AS nombre, active, check_number, check_type
  FROM l10n_latam_identification_type WHERE active;

SELECT l10n_latam_identification_type_id AS tipo, count(*)
  FROM res_partner WHERE vat IS NOT NULL AND vat <> ''
 GROUP BY 1 ORDER BY 2 DESC;

-- 2.4) Cédulas duplicadas en la base (el módulo las resuelve, pero conviene verlas)
SELECT vat, count(*) AS veces, string_agg(id::text, ',' ORDER BY id) AS ids
  FROM res_partner
 WHERE l10n_latam_identification_type_id = <TIPO_DOC> AND vat IS NOT NULL AND vat <> ''
 GROUP BY vat HAVING count(*) > 1 ORDER BY veces DESC;

-- 2.5) unaccent instalado (hace falta para resolver los departamentos)
SELECT count(*) FROM pg_extension WHERE extname = 'unaccent';

-- 2.6) Departamentos de Uruguay cargados
SELECT count(*) FROM res_country_state
 WHERE country_id = (SELECT id FROM res_country WHERE code = 'UY');

-- 2.7) Espacio en las secuencias (int4 aguanta hasta 2.147.483.647)
SELECT last_value FROM res_partner_id_seq;
SELECT last_value FROM loyalty_card_id_seq;
```

### 3. Verificar el CSV desplegado

```sh
shasum -a 256 forum_partner_import/data/forum_clientes_puntos_20260831.csv
# tiene que dar c2bae129efdca336c19d407d6d69221b70af9c17f653258b3a440783ef44f82e
```

El form también lo valida solo: muestra la ruta del archivo dentro del módulo y
un diagnóstico, y no deja cargar si no lo encuentra o no puede leerlo.

### 4. Después de cargar el staging, antes de iniciar

El resumen del log ya trae lo importante; se puede ampliar con:

```sql
-- Discrepancias entre la columna "Acción" del CSV y la realidad de la base
SELECT accion, accion_efectiva, count(*)
  FROM forum_import_staging_<ID> GROUP BY 1, 2 ORDER BY 1, 2;

-- Filas que van a quedar sin departamento (esperable: "Extranjero")
SELECT departamento, count(*) FROM forum_import_staging_<ID>
 WHERE state_id IS NULL AND departamento IS NOT NULL GROUP BY 1 ORDER BY 2 DESC;

-- Cuántas tarjetas van a hacer falta vs. el pool
SELECT count(*) FROM forum_import_staging_<ID>
 WHERE puntos_int > 0 AND accion_efectiva IN ('crear', 'actualizar');
```

## Cómo revertir

La tabla staging es el registro de todo lo que se tocó: guarda el `partner_id`
y el `card_id` de cada fila. **No borrarla hasta estar conforme con el
resultado.**

> **Para revertir una corrida completa, restaurar el dump del paso 1 del
> checklist.** El borrado de los
> contactos en el lugar es inviable a este volumen: hay **124 claves foráneas
> apuntando a `res_partner`, 61 de ellas sin índice** en la columna que
> referencia, así que cada contacto borrado fuerza un scan de esas tablas.
> Medido sobre la base de prueba: **27 s cada 500 contactos**, o sea unas **8
> horas** para 543.000. Creando un índice en `loyalty_card.earned_partner_id`
> —el peor caso, 521.000 filas sin índice— baja a 11,5 s cada 500, que siguen
> siendo ~3,5 horas.

Los pasos de abajo sirven para revertir **corridas parciales** o para deshacer
solo la parte de tarjetas, que sí es rápida.

### Devolver las tarjetas a su estado anterior (rápido, verificado)

```sql
CREATE TEMP TABLE bk (id int, code varchar, points float, partner_id int, program_id int);
\copy bk FROM '/tmp/loyalty_card_backup_prog2_XXXXXXXX.csv' WITH (FORMAT csv, HEADER true)

-- Restaura puntos y titular de las que ya existían
UPDATE loyalty_card c SET points = b.points, partner_id = b.partner_id
  FROM bk b WHERE c.id = b.id;

-- Borra las que creó la importación (las que no están en el backup)
DELETE FROM loyalty_card c
 WHERE c.id IN (SELECT card_id FROM forum_import_staging_<ID> WHERE card_id IS NOT NULL)
   AND NOT EXISTS (SELECT 1 FROM bk b WHERE b.id = c.id);
```

Verificado en seco sobre la corrida de prueba: restauró las 416.457 tarjetas
del backup e identificó exactamente las 105.260 creadas por la importación.

### Borrar los contactos creados (lento — ver la advertencia de arriba)

Conviene hacerlo por lotes con commit, para no sostener una transacción de
horas. Antes, el índice que más pesa:

```sql
CREATE INDEX IF NOT EXISTS loyalty_card_earned_partner_id_idx
    ON loyalty_card (earned_partner_id);
```

```sql
-- Repetir hasta que no borre más filas
DELETE FROM ir_property
 WHERE res_id IN (SELECT 'res.partner,' || partner_id
                    FROM forum_import_staging_<ID>
                   WHERE accion_efectiva = 'crear' AND partner_id IS NOT NULL
                   LIMIT 5000);

DELETE FROM res_partner
 WHERE id IN (SELECT partner_id FROM forum_import_staging_<ID>
               WHERE accion_efectiva = 'crear' AND partner_id IS NOT NULL
               LIMIT 5000);
COMMIT;
```

Después de revertir por SQL, reiniciar el servidor para limpiar caches.

## Volver a correr

Es seguro: la segunda corrida re-verifica contra la base y las cédulas ya
importadas pasan a `actualizar`, no a `crear`. Probado — en la segunda pasada
sobre el mismo archivo, `crear = 0` y no se duplicó ningún contacto.

Tener en cuenta que la carga del staging es más lenta cuanto más grande esté
`res_partner` (39 s con 104.000 contactos, 78 s con 647.000), porque el join de
matching crece.

## Hallazgos colaterales

Verificando el procedimiento de reversión apareció algo que excede a este
módulo: **61 de las 124 claves foráneas que apuntan a `res_partner` no tienen
índice**, y una de ellas —`loyalty_card.earned_partner_id`, 521.875 filas— la
consulta el POS en cada cierre de orden, con un scan secuencial de 188 ms.
Está documentado y medido en **`FINDINGS.md`**, con el índice sugerido. No se
aplicó nada: es insumo para decidir.

## El archivo CSV

Vive en `data/forum_clientes_puntos_20260831.csv` y el módulo **siempre** lee
ese nombre. No se declara en el manifest (no son registros de Odoo), no se sube
por la interfaz y no se guarda como adjunto: se lee del filesystem con
`odoo.tools.file_path`, que es la utilidad vigente en Odoo 17.

El archivo **se versiona junto al código**, para que el deploy por `git pull`
deje el CSV auditado con el módulo. Huella del archivo commiteado:

```
sha256  c2bae129efdca336c19d407d6d69221b70af9c17f653258b3a440783ef44f82e
tamaño  81.067.880 bytes (77 MB)
filas   646.074 (646.073 de datos + cabecera)
```

Para verificarlo después de un deploy:

```sh
shasum -a 256 forum_partner_import/data/forum_clientes_puntos_20260831.csv
```

El módulo además **valida en runtime** que el archivo exista y sea legible por
el usuario del servidor antes de dejar arrancar: el form muestra la ruta
resuelta y un diagnóstico, y el botón de carga se bloquea si algo falla.

Formato: ISO-8859-1, separador `;`, terminadores CRLF, con cabecera. La
conversión de encoding la hace PostgreSQL (`ENCODING 'LATIN1'` en el `COPY`),
así que el archivo se streamea sin decodificarlo en Python ni cargarlo entero
en memoria.

Para reemplazarlo por una versión nueva, pisar el archivo respetando el nombre
(y actualizar el sha256 de arriba), o cambiar `NOMBRE_CSV` en
`models/forum_import_batch.py`.

---

# Ajuste de inventario

Ajuste de inventario multi-sucursal a partir del conteo físico del 12/09/2026.
Código en `models/forum_import_batch_inventario.py` (carga) y
`models/forum_import_batch_inventario_apply.py` (aplicación).

Son **dos fases**, cada una con su botón, su puntero y su barra en el widget:

| fase | qué hace | cómo | toca contabilidad |
|---|---|---|---|
| 1. Carga del conteo | escribe la cantidad contada en cada quant, como si alguien la tipeara en *Inventario físico* | SQL por tandas | no |
| 2. Aplicación | crea el movimiento de cada quant con diferencia, su valuación y su asiento | ORM (`_apply_inventory`) por tandas | sí |

La fase 1 se puede revisar y repetir sin consecuencias. La fase 2 es la que
mueve stock y valuación, y **no se hace por SQL**: las capas FIFO, la valuación
y los asientos los resuelve el ORM.

## Flujo de uso

1. **Contactos → Importación FORUM → Crear**, Tipo de importación **Ajuste de
   inventario**. Completar **Responsable del conteo** (tiene que ser
   administrador de inventario: es el usuario con el que se aplica) y, si hace
   falta, **Fecha contable del ajuste** (ver abajo).
2. **1. Cargar staging** — lee el xlsx y arma `forum_import_staging_<id>`. El log
   resume acciones, ubicaciones por compañía y cada motivo de ignorado/error.
3. **2. Cargar conteo en los quants** — fase 1.
4. Revisar. `Exportar errores e ignoradas` baja un CSV con fila y columna del
   Excel, el ID externo y el motivo de cada celda que no se va a tocar.
5. **3. Aplicar ajuste por tandas** — fase 2. **De noche, con las sucursales
   cerradas** (ver *Requisitos operativos*).

**Medido sobre una copia de o17_support_forum (2026-09-15):**

| etapa | tiempo |
|---|---|
| Armado del staging (lectura del xlsx + pre-proceso) | 25,7 s |
| Fase 1: 930.892 celdas en tandas de 5.000 | 37 s |
| Fase 2: tandas de 2.000 quants | ~60 s por tanda (~30 ms por quant) |

## El archivo

`data/ajuste_inventario_20260912.xlsx`, copia del "Cuadro de doble entrada -
Ajuste de Inventario.xlsx" original. Como el CSV de clientes: versionado con el
código, ruta relativa al módulo resuelta con `odoo.tools.file_path`, y el form
valida que exista y sea legible antes de dejar cargar.

```
sha256  ff597ab900ab0d0c0ed39cb3b0fcd3ef7a91ddbe680b1aa666cea6a2e666d61b
tamaño  8.290.009 bytes
```

Es una **tabla de doble entrada**, primera hoja:

| fila | contenido |
|---|---|
| 1 | nombre del almacén, desde la columna F (39 sucursales) |
| 2 | `complete_name` de la ubicación de existencias de cada sucursal (`POLO/Existencias`, `032/PAYSANDU/Existencias`, …). **Es la clave de matching** |
| 3 | cabecera de producto: `id` (ID externo), `default_code`, `name`, `product_tmpl_id/name`, `product_template_variant_value_ids` |
| 4+ | una variante por fila (23.870). En el cruce con cada columna, la cantidad contada |

Se lee con **openpyxl en modo `read_only`**, fila por fila, sin armar la hoja en
memoria, y se **des-pivotea**: cada celda con valor pasa a ser una fila de staging
(producto, ubicación, cantidad), que entra con un solo `COPY`. openpyxl no está
en los requirements de Odoo 17 (base_import lo importa como opcional): está
declarado en `external_dependencies`, así que el módulo no instala sin él.

El formato se valida antes de cargar nada: `id` en A3, ubicaciones no vacías y
sin repetir en la fila 2, y ninguna cantidad en una columna sin ubicación.

## Resolución

Todo set-based, en el armado del staging:

1. **Ubicaciones** — fila 2 contra `stock_location.complete_name` exacto, entre
   las activas. **Bloqueante**: si una sola no resuelve, no es interna, está
   repetida o no tiene compañía, no se carga nada y el log dice cuáles.
2. **Productos** — el ID externo se separa en módulo y nombre y se busca en
   `ir_model_data` (`model = 'product.product'`). **No** se usa el número
   embebido en `__export__.product_product_<n>_…`: el id externo es la fuente de
   verdad.
3. **Filtro** — se **ignoran con motivo** (no son error) las variantes no
   almacenables (`type <> 'product'`: consumibles, servicios) y las que tienen
   seguimiento por lote o número de serie, que no se pueden ajustar en un quant
   sin lote.
4. **Errores** — ID externo inexistente, ID externo de otro modelo, cantidad no
   numérica o negativa, producto de otra compañía que la ubicación, y el mismo
   par producto/ubicación repetido en el archivo (gana la primera fila).
5. **Quant existente** — el quant sin lote, paquete ni propietario de cada par.

En la base de prueba: **313 IDs externos no existen** (productos creados después
del dump; 12.207 celdas, quedan como error) y **16 variantes no son almacenables**
(15 servicios —descuentos, gastos de hr_expense, la línea de descuento de
pos_forum_birthday_promo— y el consumible del POS; 624 celdas ignoradas). Con un
dump fresco de producción esos números cambian: el módulo no los tiene fijos.

### La semántica del 0

**Al revés que en clientes.** En clientes un 0 de puntos es "no tocar". Acá un 0
es un dato: *en esta sucursal este producto no hay*.

- **Celda vacía** → no genera línea: esa sucursal no se toca para ese producto.
- **Celda con 0 y el producto tiene quant** → el quant queda contado en 0 y el
  ajuste lo lleva a 0.
- **Celda con 0 y no hay quant** → *en cero sin quant*: ya está en cero, no se
  crea nada. En la aplicación se vuelve a mirar por si apareció un quant.

### Multicompañía

Los nombres de almacén traen razones sociales distintas (Neratur, Faringol,
Gaimta, Aweryl, Matias Coore), pero **en la base las 39 ubicaciones y sus
almacenes son de la compañía 1 (FORUM, polo oeste)**. La razón social es solo
informativa: FORUM es una compañía operativa que explota tiendas de varios RUTs.

Igual el módulo **no asume la compañía**: cada celda toma el `company_id` de su
ubicación (el quant lo necesita igual al de la ubicación, es un related stored)
y la aplicación agrupa por compañía para valuar con la correcta. El log de carga
muestra el reparto de ubicaciones por compañía.

## Fase 1: carga del conteo

Upsert de `stock_quant` por tandas de celdas. En cada tanda:

1. `LOCK TABLE stock_quant IN SHARE ROW EXCLUSIVE MODE`, décimas de segundo. Sin
   esto, una venta del POS podría crear el quant del mismo par entre el
   "¿existe?" y el INSERT: el par quedaría partido en dos quants, el ajuste
   corregiría uno solo y el total no daría el contado. `stock_quant` **no tiene
   constraint de unicidad**.
2. Se vuelve a buscar el quant de cada par (pudo aparecer o desaparecer desde el
   pre-proceso). Si hay más de uno, la celda queda como error.
3. Existe → `inventory_quantity` = contado, `inventory_diff_quantity`,
   `inventory_quantity_set`, `inventory_date`, `user_id` y `reason`.
4. No existe y el contado no es 0 → `INSERT` con `quantity = 0` (stock
   desconocido: para el sistema es 0) y los NOT NULL y stored del modelo real:
   `company_id` y `storage_category_id` de la ubicación, `reserved_quantity`,
   `in_date`, y lo que agregan otros módulos (la moneda de reportes de
   tchistorico, `reason` de stock_change_qty_reason). Esos extras no están
   listados a mano: se leen de `stock.quant._fields`.

**Idempotente.** Probado: una segunda carga del mismo archivo sobre la misma base
dio 0 quants creados, 835.309 actualizados y el mismo total de quants, sin
duplicados.

**Motivo.** `stock_change_qty_reason` está instalado: el campo `reason` del quant
viaja al origen de cada movimiento. Se completa solo con
`Ajuste inventario FORUM 12/09/2026 - batch <id>` si no se escribe otro.

## Fase 2: aplicación

Lo mismo que el botón *Aplicar* de Inventario físico, pero por tandas:

- **Una tanda por corrida del cron** (default 2.000 quants), con commit, y
  `_trigger()` para la siguiente.
- **Ordenado por ubicación** (columna del Excel): cada sucursal queda bloqueada
  en un solo tramo.
- En cada tanda se bloquean los quants (`FOR NO KEY UPDATE`), se pone el contado
  y **se recalcula la diferencia contra la cantidad de ese momento**.
- Sin diferencia → se limpia el conteo, sin movimiento. Con diferencia →
  `_apply_inventory()` de toda la tanda; si falla, **quant por quant, cada uno en
  su savepoint**, y solo los que fallan quedan como error (con el mensaje en
  staging y en el export). Esos quants conservan el conteo en Inventario físico.
- Si un par tiene más de un quant, se fusionan con `_merge_quants` del core
  antes de ajustar.
- Un choque de concurrencia (serialización, deadlock) **reintenta la tanda**
  hasta 3 veces antes de marcar error: la tanda se revierte entera, así que
  repetirla es seguro.

**Verificado** sobre las primeras tandas: las 5.556 celdas aplicadas quedaron
con cantidad = contado, conteo limpio, el motivo en el origen del movimiento y
su capa de valuación; 11 asientos para los productos con costo.

**Cancelar** durante la aplicación es un *pedido*: la tanda en curso termina y
lo ya aplicado queda. No escribe la fila del batch a propósito: la tanda en curso
la escribe al terminar, y dos escrituras concurrentes sobre la misma fila hacían
fallar el commit de la tanda entera (pasó en la prueba: se perdía un minuto de
trabajo y el batch quedaba en error). **Reanudar** retoma desde el puntero. Si el
servidor se cae a mitad de tanda, esa tanda se revierte y el cron la retoma solo
(probado: puntero en 6.000, 5.556 movimientos, coherente).

### Fecha contable

**Fecha contable del ajuste** (`inventory_accounting_date`): si está vacía, los
movimientos y asientos llevan la fecha en que se aplica; si tiene valor, se
aplica con `accounting_date` (el mismo mecanismo de *Inventario físico*). **La
decide el contador del cliente antes de producción.**

### Asientos

Cada movimiento con valor en una categoría con valuación automática genera **un
asiento por quant**, en el diario de stock. En la base de prueba casi ningún
producto tiene costo (69 de 23.541), así que casi no hay asientos; con costos
cargados pueden ser cientos de miles. **Pendiente de confirmación del cliente.**
`aml_secondary_currency` exige tipo de cambio de la moneda secundaria para la
fecha del asiento: en producción lo carga el cron del BCU; en la copia de prueba
hubo que cargar el del día a mano.

### Cuánto tarda, y por qué

~30 ms por quant en la copia de prueba, o sea **~7-8 horas para las 918.061
celdas**. El que pesa es **`tchistorico`**: `stock.quant.value_report` es un
calculado stored que depende de las capas de valuación **del producto**, así que
cada movimiento recalcula todos los quants de ese producto (~35 por producto
después de la carga) y cada uno hace su propia búsqueda. Perfilado sobre 200
quants, con rollback:

| | por quant | consultas |
|---|---|---|
| tal cual | 69 ms (con profiler) | 10.194 |
| sin el recompute de `value_report` | 17 ms | 3.374 |

No se tocó `tchistorico`. Si la ventana nocturna no alcanza, las opciones son
diferir ese recompute durante el ajuste (cambio en `general_primate`) o partir
la aplicación en varias noches: el puntero y **Reanudar** lo permiten, y cada
tanda deja la base consistente.

## Requisitos operativos

- **De noche, con las sucursales cerradas.** Cada tanda de la aplicación bloquea
  los quants que ajusta durante ~1 minuto y compite con el POS por esos locks.
- **Carga y aplicación en la misma ventana.** La aplicación deja la cantidad
  final igual al contado. **Limitación explícita:** lo que se venda entre el
  conteo físico y la aplicación queda absorbido por el ajuste.
- **Dump verificado antes de aplicar** (mismo procedimiento que en clientes). La
  aplicación crea movimientos, valuación y asientos: la vuelta atrás real es
  restaurar el dump.
- **Responsable del conteo** administrador de inventario.

## Alcance explícito del ajuste

Lo que **no** toca, a propósito:

- **Variantes no almacenables y con lote/serie** — ignoradas con motivo.
- **Quants con paquete o propietario** — el conteo va al quant *suelto* de la
  ubicación. Un producto que además tenga stock en un paquete en esa ubicación
  queda con el contado **más** lo del paquete (23 quants con paquete en la base
  de prueba).
- **Ubicaciones que no están en el archivo** — sububicaciones (ej.
  `POLO/Existencias/Cajas Cerradas`), `POLO/Entrada`, las salidas, "Auditoría -
  Diferencias", los almacenes de otras compañías: nada de eso se ajusta.
- **Celdas vacías** — esa sucursal no se toca para ese producto.

Diferencia menor con el botón de la UI: un quant **sin diferencia** se limpia sin
crear el movimiento de cantidad 0 ("Product Quantity Confirmed") que crearía
*Aplicar*, así que su fecha de último conteo no se actualiza.

## Checklist pre-producción

1. **Dump verificado** (ver el de clientes).
2. `python3 -c "import openpyxl"` en el entorno del servidor.
3. `shasum -a 256 forum_partner_import/data/ajuste_inventario_20260912.xlsx`
   contra la huella de arriba.
4. Tipo de cambio de la moneda secundaria cargado para la fecha contable.
5. Después de cargar el staging, revisar el log y el export: IDs no encontrados
   (en producción deberían ser 0), ubicaciones por compañía, no almacenables.
6. Confirmar con el contador la fecha contable y los asientos.
7. Estimar la aplicación con las primeras tandas (el widget muestra ritmo y ETA)
   y decidir si entra en una noche.
