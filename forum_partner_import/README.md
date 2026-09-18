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
| 2. Aplicación | crea el movimiento de cada quant, su línea, su capa de valuación y, si corresponde, su asiento | SQL por tandas, con los productos valorizados por el ORM (`_apply_inventory`) | sí (solo vía ORM) |

La fase 1 se puede revisar y repetir sin consecuencias. La fase 2 mueve stock:
va por SQL **replicando campo por campo lo que hace el ORM**, validado con una
prueba de paridad contra `_apply_inventory`. Todo lo que tiene valuación
distinta de cero —y por lo tanto asientos— sigue yendo por el ORM.

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
| Fase 2: tanda de 50.000 celdas (SQL + ORM) | ~16 s |
| Fase 2 completa: 904.061 celdas + recálculos finales | **5 min 37 s** |

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

**Motivo.** Se completa solo con `Ajuste inventario FORUM 12/09/2026 - batch <id>`
si no se escribe otro, y va al origen de cada movimiento. El campo `reason` del
quant y de la línea de movimiento lo agrega `stock_change_qty_reason` (OCA), que
en Forum está instalado. **Es una dependencia blanda**: no está en `depends`; si
el módulo no está, el ajuste funciona igual y el motivo queda solo en el origen.

## Fase 2: aplicación

La primera versión aplicaba por el ORM (`_apply_inventory`) en tandas: ~30 ms por
quant, **7-8 horas**, casi todo recompute de tchistorico. Ahora la aplicación va
por SQL set-based y el ORM queda solo para lo que tiene valuación.

### La disección (la spec de la réplica)

Se aplicó por el ORM, con rollback, un quant de cada caso —alta pura, alta con
capas FIFO, suba, baja con consumo FIFO, quant negativo, contado 0 con stock,
diferencia 0, reserva, producto con costo en tiempo real (alta y baja), producto
con capa negativa— y se registró **todo** lo que la transacción escribió
(`pg_stat_xact_user_tables`, filas nuevas y antes/después). Lo que hace
`_apply_inventory` por quant:

| qué | detalle |
|---|---|
| `stock.move` + `stock.move.line` en `done` | nombre `Product Quantity Updated (<responsable>)`, origen = motivo, `reference` = nombre, `priority '0'`, `picked`, `is_inventory`, `date` a segundos. **Con diferencia 0 igual crea un movimiento de cantidad 0** (`Product Quantity Confirmed`) |
| sentido | diferencia > 0: ubicación de ajuste de inventario → existencias; si no, al revés |
| quant contado | `quantity += diferencia`; conteo limpio; `inventory_date` = próxima fecha de inventario de la ubicación; `reason`/`user_id` en NULL. `in_date`: en una entrada, el más viejo entre el suyo (si tenía stock) y ahora; en una salida, el suyo (si tenía stock) o ahora |
| quant de la ubicación de ajuste | `quantity -= diferencia`; `in_date` de la última línea del producto (orden de id). Si no existe se crea: su `inventory_diff_quantity` es −(cantidad final) y su `unit_value_report` queda NULL |
| `stock.valuation.layer` | una por movimiento con cantidad, **aunque valga 0**: primero todas las entradas, después las salidas, que consumen FIFO (`create_date, id`) las capas con saldo, incluidas las recién creadas. Salida cubierta: `remaining_qty 0`, `remaining_value NULL` |
| ubicación | `last_inventory_date` = hoy |
| cascadas | `value_report` (tchistorico) en **todos** los quants del producto, `ultimo_costo_mr` del producto y la plantilla, `qty_to_order` de los puntos de reorden |

Lo que **no** hace, y se verificó: `_trigger_assign` (reservar movimientos en
espera) solo lo llama el `_action_done` del picking; los movimientos de
inventario no tienen picking.

#### La disección de la valuación con valor y de los asientos

Para el escenario de saldos iniciales se disecó además lo que el core genera
**cuando la capa tiene valor**, leyendo `stock_account` caso por caso y
comparando contra el ORM sobre la copia:

| qué | detalle |
|---|---|
| capa de **entrada** | `value` = `cantidad × standard_price` redondeado a la moneda de la compañía (`_prepare_in_svl_vals`). El costo sale de `standard_price` porque un movimiento de inventario nace sin `price_unit` y `_get_price_unit` cae ahí. `remaining_qty` = cantidad, `remaining_value` = su propio valor |
| capa de **salida** (FIFO) | `value` = **−Σ de lo tomado de cada capa candidata**, con **cada toma redondeada por separado** (`currency.round(value_taken_on_candidate)` dentro del bucle de `_run_fifo`); `unit_cost` = `tmp_value / cantidad`, **no** el costo del producto. El costo de cada candidata es `remaining_value / remaining_qty`, no su `unit_cost`. Orden de consumo: `create_date, id` (el `_order` del modelo, que es el que usa `_get_fifo_candidates`) |
| candidatas consumidas | se les descuenta `remaining_qty` **y** `remaining_value` (`candidate_vals` de `_run_fifo`) |
| **stock negativo** | si las candidatas no alcanzan: `remaining_qty` = −faltante y el faltante se valúa al `last_fifo_price`, que es el costo de la **última candidata mirada aunque valga 0** (en Python `0.0` es falsy, así que ahí sí actúa el `or standard_price`) |
| `remaining_value` de una salida | **NULL siempre**, también con faltante: ni `_prepare_out_svl_vals` ni `_run_fifo` escriben ese campo (la rama de faltante devuelve `remaining_qty`, `value` y `unit_cost`) |
| tchistorico | con valor, su `create()` calcula `cotizacionDia`, `valorMonedaSecundaria`, `valorRestante`, `valorUnitario`, `moneda_reporte_id`, `unitCostesDestinoInc` (= `value/cantidad` en una entrada, `value` pelado en una salida), `unitCostesDestinoIncMR`, `valorizadoCosteDestino`, `valorizadoCosteDestinoMR`; y `ucmr` y `unit_cost_report` se asignan **siempre**, incluso sin cotización (quedan en 0) |
| `account.move` | **uno por capa** cuyo producto valúa en tiempo real y cuyo valor no es cero (`_validate_accounting_entries`), `move_type='entry'`, en el diario de stock de la categoría, `ref` = nombre del movimiento, `stock_move_id` al movimiento, sin partner (`_get_partner_id_for_valuation_lines` sale del picking) |
| `account.move.line` | dos líneas por asiento, `debit`/`credit` por el importe absoluto de la capa, `quantity` con el signo de la capa en **las dos**, `display_type='product'`, `sequence` 100. En una entrada debita valuación y acredita la contrapartida; en una salida al revés. La contrapartida de una ubicación de ajuste es `stock_output` de la categoría salvo que la ubicación tenga la suya (`_get_dest_account`) |
| numeración | el `name` y el `sequence_prefix/number` los asigna el ORM **al publicar**, no al crear |

### Réplica SQL + híbrido ORM

Por cada tanda (default **50.000 celdas**, una por corrida del cron):

1. `LOCK TABLE stock_quant` y `stock_valuation_layer` en `SHARE ROW EXCLUSIVE`
   mientras dura la tanda: nadie crea ni mueve quants o capas mientras el SQL
   decide sobre ellos. **Con la valuación adentro la tanda pasó de ~16 s a
   ~41 s** (ver *Cuánto tarda* y *Requisitos operativos*).
2. **Clasificación por producto.** Va por el ORM, con todas sus celdas de la
   tanda, solo el producto que tenga: **capas negativas preexistentes** (las
   corrige el `_fifo_vacuum`, que el SQL no replica), **reservas** o **líneas
   pendientes** en la ubicación (`_free_reservation`), **costeo que no sea
   FIFO**, **seguimiento por lote**, par sin quant o con quants duplicados.

   **Tener costo ya NO manda al ORM**, y es el cambio de fondo de esta versión:
   en el escenario de saldos iniciales *todos* los productos tienen costo, así
   que con el criterio anterior caía el **100 %** de las celdas al camino lento
   (medido: 50.000 de 50.000 en una tanda, 30-49 ms por celda, 8-12 h para las
   918.061). Ahora caen **6.404 celdas de 918.061: 0,7 %**.
3. **SQL** para el resto: `stock_move`, `stock_move_line`, quants, quant de
   ajuste, **capas con valor**, **consumo FIFO**, **asientos en borrador** y
   ubicación, con la diferencia recalculada contra la cantidad de ese momento.

#### Las capas con valor

- **Entrada:** `cantidad × costo`, redondeado a la moneda de la compañía, como
  `_prepare_in_svl_vals`. El costo es el `standard_price` del producto en su
  compañía: un movimiento de inventario nace sin `price_unit`, así que
  `_get_price_unit` cae ahí.
- **Salida:** el reparto FIFO. Cada capa candidata aporta a
  `remaining_value / remaining_qty` —su costo real, no su `unit_cost`— y **cada
  toma se redondea por separado**, como el `currency.round(value_taken_on_candidate)`
  de adentro del bucle de `_run_fifo`. El `unit_cost` de la capa de salida es
  `tmp_value / cantidad`, no el costo del producto.
- **Stock negativo:** lo que las capas con saldo no cubren se valúa al
  `last_fifo_price`, que es el costo de la última candidata mirada **aunque
  valga 0** (en Python `0.0` es falsy y ahí sí actúa el `or standard_price`).
- El `remaining_value` de una capa de **salida** queda **NULL siempre**, también
  con faltante: ni `_prepare_out_svl_vals` ni `_run_fifo` escriben ese campo.
- El INSERT de capas va en **dos pasos, entradas y después salidas**, porque el
  ORM valúa primero todas las entradas del lote y **las capas recién creadas son
  candidatas del FIFO de las salidas de la misma tanda**. Insertarlas juntas
  daba valores distintos.
- El consumo descuenta `remaining_qty` **y** `remaining_value` de las
  candidatas (con capas en cero el segundo no hacía falta).
- Los campos que **tchistorico** calcula en su `create()` se replican con la
  misma fórmula, porque el INSERT por SQL no pasa por ahí: `cotizacionDia`,
  `valorMonedaSecundaria`, `valorRestante`, `valorUnitario`, `moneda_reporte_id`,
  `unitCostesDestinoInc`, `unitCostesDestinoIncMR`, `valorizadoCosteDestino`,
  `valorizadoCosteDestinoMR`, `ucmr` y `unit_cost_report`, incluida su rama sin
  cotización (todo en 0 y la moneda en NULL). La cotización se calcula como
  `tasa(moneda de reporte) / tasa(moneda de la compañía)`, que es lo que hace
  `_get_conversion_rate`.

#### Los asientos, en borrador

Un asiento por capa con valor, con el mismo filtro que
`_validate_accounting_entries`: producto con valuación **en tiempo real** y valor
distinto de cero. Dos líneas que se cancelan, cuentas y diario de la categoría
del producto (`_get_accounting_data_for_valuation`); en una entrada debita
valuación y acredita la contrapartida, en una salida al revés. Sin partner:
`_get_partner_id_for_valuation_lines` sale del picking y un movimiento de
inventario no tiene.

Quedan **en borrador, sin `name` ni numeración**: eso lo asigna el ORM al
publicar. Si un producto que valúa en tiempo real no tiene cuentas o diario, la
tanda **corta con `UserError`** en vez de dejar capas con valor sin asiento, que
es lo que hace el ORM.

En `account.move.line` casi todo lo que importa es compute/related stored
(`account_id`, `balance`, `debit`, `credit`, `date`, `name`, `quantity`,
`display_type`…), así que va **explícito**; en `account.move` los 95 campos
restantes los cubre `default_get`, para que entre lo que agregue cualquier módulo
instalado (los `cfe_*` de la localización, `extract_state`, etc.).

4. **ORM** para los casos especiales: `_apply_inventory` de la tanda; si falla,
   quant por quant con savepoint. **Todo el camino ORM va con el guard del WMS**
   (ver *Requisitos operativos*).

### Fase 3: publicación de los asientos

Publicar va **por el ORM y no por SQL, a propósito**: la numeración del diario es
correlativa legal y el balanceo y los hooks los tiene que firmar Odoo. La fase
no hace nada más que `action_post` por tandas, con puntero, commit por tanda,
cancelar/reanudar y reintento por asiento con savepoint.

**El tamaño de tanda es configurable y su default, 150, es el óptimo MEDIDO.**
Agrandar la tanda **empeora** el total, que es lo contrario de lo que uno espera:
el costo por asiento de `action_post` crece con el tamaño del lote porque
`_check_balanced` y los recomputes recorren todo el conjunto en memoria.

| asientos por tanda | ms por asiento | extrapolado a 834k |
|---|---|---|
| 25 | 7,91 | 121 min |
| 50 | 6,43 | 98 min |
| 100 | 5,36 | 82 min |
| **150** | **4,95** | **76 min** |
| 200 | 5,34 | 82 min |
| 300 | 6,07 | 93 min |
| 2.000 | 11,53 | 176 min |

**No subirlo sin volver a medir.** Un "5.000 para que vaya más rápido" duplica
el tiempo.

Antes de arrancar, la fase **valida que exista la cotización de la moneda
secundaria para la fecha exacta de los asientos** y frena con el detalle si
falta, en vez de fallar a mitad de tanda (ver *Requisitos operativos*).

**Agrupar asientos** —uno por producto o por categoría en vez de uno por capa—
bajaría mucho el tiempo, pero **cambia lo que ve el contador** y no se
implementó: queda como opción futura, sujeta a decisión del cliente.

### Verificación exhaustiva por invariantes

Al terminar la aplicación, y otra vez al terminar la publicación, el módulo corre
por SQL un set de invariantes **sobre el 100 % de lo generado** —no un muestreo—
y guarda el resultado en el batch (`check_state`, `check_report`). Si alguno
falla, el informe lista las violaciones con ejemplos.

| # | Invariante |
|---|---|
| 1 | `quant.quantity` = contado del archivo, en todas las celdas aplicadas |
| 2 | cada celda aplicada tiene su movimiento `done` con su línea |
| 3a | entrada: `value` = cantidad × costo |
| 3b | ninguna capa con `remaining_qty` > cantidad |
| 3c | `remaining_value` NULL o 0 en las salidas |
| 4a | ninguna capa con valor sin asiento |
| 4b | ningún asiento desbalanceado (Σdébitos = Σcréditos) |
| 4c | el importe del asiento es el valor de su capa |
| 4d | las cuentas son las de la categoría del producto |
| 5a | ningún asiento del ajuste quedó en borrador (tras publicar) |
| 5b | ninguna numeración duplicada en el rango del ajuste |
| 5c | ningún hueco en la numeración del diario en ese rango |
| 6a | ningún par producto/ubicación con más de un quant |
| 6b | ningún conteo pendiente sin aplicar |
| 7 | **ningún envío nuevo al WMS** en `product_wms_log`, `wis_sync_queue` ni `wms_integracion_log` |
| 8 | Σ del diario = Σ de las capas |

El 5b y el 5c se miran sobre **todo el diario en el rango del ajuste**, no solo
sobre los asientos del ajuste: el diario puede tener asientos ajenos
intercalados y compararlos solo entre ellos daba huecos inexistentes.

El invariante 7 se apoya en una **línea base** de esas tres tablas que se guarda
al arrancar la aplicación: no alcanza con mirar la configuración, porque
`wis.sync.queue._encolar` escribe sin consultar si la comunicación está
habilitada.

### Paridad con el ORM (criterio de aceptación)

**Cómo se hace.** Dos **copias gemelas** de la misma base pre-apply
(`o17_par_sql` y `o17_par_orm`), preparadas con el mismo script: neutralizadas
(correo, crons y WMS), con el peor caso de costeo cargado y la fase 1 corrida.
En una se aplica el subconjunto por el **camino SQL** y en la otra **el mismo
subconjunto** por `_apply_inventory`; cada lado vuelca a un archivo lo que
generó, y un comparador diffea los dos archivos **campo a campo**.

Se hace en dos bases y no con savepoints en una sola porque el diff cruzado
entre bases no se puede hacer en una sesión de Postgres, y porque una gemela por
camino garantiza que ningún lado vea estado del otro.

**El subconjunto lo elige una consulta determinista e idéntica en las dos**:
productos que el SQL sí maneja (los del camino ORM van por ORM en las dos
gemelas y coincidirían por construcción, no probarían nada), con **entradas,
salidas y contado 0** entre sus celdas, y **solo celdas con quant**. Ese último
filtro no es un detalle: una celda de contado 0 sin quant la descarta el SQL y en
cambio el ORM le crea el quant y un movimiento de **cantidad 0**; sin el filtro
el diff acusa cientos de filas de diferencia que son del arnés y no del motor.

**Qué se normaliza, y por qué.** Los ids y los timestamps, porque son
autogenerados; la **fecha** del asiento, porque las gemelas pueden correr en días
distintos del reloj; y el **estado** del asiento, porque el ORM publica dentro de
`_validate_accounting_entries` mientras el SQL los deja en borrador a propósito
(los publica la fase 3). Todo lo demás se compara, y **los numéricos por su
representación exacta**: `6.00` y `6` son distintos aunque valgan lo mismo.

**Tablas que se comparan:** `stock_move`, `stock_move_line`,
`stock_valuation_layer` (incluidos los diez campos de tchistorico),
`account_move`, `account_move_line` y `stock_quant`.

**Lo que la paridad encontró y se corrigió.** Dos defectos reales de la réplica,
los dos en la parte de tchistorico, que ningún invariante había detectado porque
son consistentes internamente:

1. **La condición de la rama era la cotización y no el valor de la capa.** El
   `create()` de tchistorico entra por su rama de entrada con `value > 0`, por la
   de salida con `value < 0`, y **todo lo demás —incluido `value = 0`— cae en el
   `else`**, que deja `cotizacionDia` en 0, `moneda_reporte_id` en NULL y los
   cuatro campos de costo destino **sin asignar (NULL, no 0)**. La réplica
   escribía cotización en capas de valor 0. De 12.610 capas de valor 0, el ORM
   dejó las 12.610 con esos campos en NULL.
2. **`unit_cost_report` se calcula con la cotización ya redondeada.** Es el único
   campo **calculado** del módulo, y el ORM lo computa **después** de guardar
   `cotizacionDia`, o sea desde el valor ya redondeado a sus 6 decimales:
   `3556 × 0,025083 = 89,195148 → 89,20`, y no `3556 × 0,025082773… = 89,19`.

**Resultado: paridad exacta, 0 diferencias.** Con los dos defectos corregidos y
el arnés simétrico, el diff sobre **73 productos y 2.589 celdas** —con entradas,
salidas y contado 0— da **idéntico campo a campo en las seis tablas**:

| tabla | filas | resultado |
|---|---|---|
| `stock_move` | 2.589 | idénticas |
| `stock_move_line` | 2.589 | idénticas |
| `stock_valuation_layer` | 2.589 | idénticas (incluidos los diez campos de tchistorico) |
| `account_move` | 2.516 | idénticas |
| `account_move_line` | 5.032 | idénticas |
| `stock_quant` | 2.662 | idénticas |

Y un **detalle de rendimiento** que la paridad dejó medido: el mismo subconjunto
tarda **1,5-1,8 s por SQL contra ~40 s por ORM**, unas 20-25 veces más.

### Verificación del después

Sobre la copia aplicada por SQL:

- **Recompute forzado** de todos los calculados stored de lo tocado (movimientos,
  líneas, capas, productos, puntos de reorden): **0 cambios**. En `stock_quant`
  cambian `inventory_diff_quantity`/`inventory_quantity_set` —recalcularlos sin un
  conteo en curso los vuelve a "contado"—, **exactamente igual en la copia
  aplicada por el ORM**: es comportamiento de esos calculados, no de la réplica.
- **Stock = contado** en las 2.356 celdas, `qty_available` del ORM coincide, y la
  suma de capas FIFO coincide con el stock interno de cada producto.
- **Movimiento posterior normal**: un picking interno sobre un producto ajustado
  por SQL se reservó y validó sin errores.
- **UI**: sobre la corrida completa, la ficha de un producto ajustado por SQL y su
  kardex (botón In/Out) abren sin errores y listan los movimientos del ajuste,
  de la ubicación de ajuste a cada sucursal, con fecha, referencia y cantidad.

### Operación

**Cancelar** durante la aplicación **o la publicación** es un *pedido*: la tanda
en curso termina y lo ya hecho queda (no escribe la fila del batch: la tanda en
curso la escribe al terminar y el choque hacía fallar su commit). **Reanudar**
retoma desde el puntero; en la publicación recuenta los borradores pendientes,
así que lo ya publicado no vuelve a pasar. Un choque de concurrencia **reintenta
la tanda** hasta 3 veces. Si el servidor se cae a mitad de tanda, esa tanda se
revierte y el cron la retoma. Un batch arrancado con una versión anterior del
módulo se puede reanudar: la tanda prepara sola las columnas que le falten al
staging.

En la publicación, además, **un asiento que no publica no frena la corrida**: se
reintenta solo y, si vuelve a fallar, queda en borrador con el motivo en el log
del batch y sigue la tanda. El invariante 5a avisa si al final quedó alguno.

Los tres botones van en orden —**2. Cargar conteo**, **3. Aplicar ajuste**,
**4. Publicar asientos**— y hay un cuarto, **Verificar invariantes**, que corre
el set a pedido sobre lo ya generado.

### Fecha contable

**Fecha contable del ajuste** (`inventory_accounting_date`): si está vacía, los
movimientos y asientos llevan la fecha en que se aplica; si tiene valor, se
aplica con `accounting_date` (el mismo mecanismo de *Inventario físico*). **La
decide el contador del cliente antes de producción.**

### Asientos

Cada capa con valor en una categoría con valuación automática genera **un asiento
en el diario de stock**. En el escenario de saldos iniciales, con costo en los
23.541 productos, son **828.541 asientos** y ~1,66 millones de líneas: el SQL los
crea **en borrador** durante la aplicación y la **fase 3** los publica por el ORM
en tandas de 150.

Que sean uno por capa es lo que hace el core. **Agruparlos** —uno por producto o
por categoría— bajaría bastante el tiempo de publicación, pero **cambia lo que ve
el contador**: queda como opción futura, sujeta a decisión del cliente, y no está
implementado.

`aml_secondary_currency` exige tipo de cambio de la moneda secundaria **para la
fecha exacta** del asiento, así que la fase 3 lo valida antes de arrancar (ver
*Requisitos operativos* y `FINDINGS.md`).

### Cuánto tarda

Medido sobre `o17_inv_med` (copia con el peor caso: los 23.541 productos del
archivo con costo y categoría en tiempo real).

**Fase 2, aplicación: 12 min 30 s** para las **918.061 celdas**, 19 tandas de
50.000, **0 errores**. Genera 834.945 quants ajustados, 827.657 capas con valor y
**827.657 asientos en borrador**. Solo **1.065 celdas (0,12 %)** van por el
camino ORM. Después: **stock = contado en las 835.309 celdas** y el cuadre
contable exacto (asientos 11.575.520.446,68 = suma de |valor| de las capas).

Por tanda de 50.000: ~41 s. Con la valuación y los asientos adentro, la tanda
pasó de ~16 s (versión sin valuar) a ~41 s.

**Fase 3, publicación: ~3 horas** para los 827.657 asientos, a **13,35 ms por
asiento**.

🔴 **Una corrección importante sobre este número.** La primera medición dio
4,95 ms/asiento y se hizo **sobre una tabla con 200 asientos**: no se sostiene a
escala. Con la tabla real (829.000 asientos y 1,66 millones de líneas) el costo
es casi tres veces mayor y la curva por tamaño de tanda es **plana**:

| asientos por tanda | ms/asiento (tabla llena) | para 817.007 asientos |
|---|---|---|
| 150 | 14,12 | 192 min |
| **500** (default) | **13,35** | **182 min** |
| 1.000 | 13,50 | 184 min |
| 2.000 | 14,21 | 193 min |

**Si se vuelve a medir, tiene que ser con la tabla en volumen real.**

Dónde se va el tiempo, perfilado por componente:

| componente | costo | qué se hizo |
|---|---|---|
| `action_post` con el nombre ya puesto | **12,37 ms/asiento** | es el piso del ORM: irreducible sin tocar la numeración |
| la numeración del diario | ~2,5 ms/asiento | `VACUUM ANALYZE` de `account_move` devolvió el index-only scan de `_get_last_sequence` (18,3 ms y 15.693 *heap fetches* → 1,7 ms y 0) |
| `search_count` de pendientes **por tanda** | 142 ms (48 con rango) | **eliminado**: eran ~13 min de puro conteo. Ojo que `search(limit=1)` es PEOR (241 ms): sin `order` el planner elige mal |
| búsqueda de la tanda | 7,1 ms → **0,7 ms** | se usa el rango de ids en vez de traversar `stock_move_id.is_inventory` |

O sea: **el cuello es el `_post` del ORM, no el bucle del módulo**, y por eso las
~3 h son estructurales. Publicar es lo que asigna la numeración correlativa del
diario, así que no se reemplaza por SQL. La publicación **no toma el lock de
quants**: puede correr con el sistema en uso, incluso al día siguiente.

Por qué la primera versión (todo por ORM) tardaba horas ya en el stock:
`stock.quant.value_report` (tchistorico) depende de las capas **del producto**,
así que cada movimiento recalculaba todos los quants del producto con una
búsqueda por quant (perfilado: 69 ms por quant tal cual, 17 ms sin ese
recompute). El motor SQL lo hace una sola vez al final.

## Requisitos operativos

- **De noche, con las sucursales cerradas y el POS sin operar.** Cada tanda de la
  aplicación toma `LOCK TABLE` sobre `stock_quant` y `stock_valuation_layer` en
  modo SHARE ROW EXCLUSIVE y lo mantiene **toda la tanda**. Con la valuación y
  los asientos adentro, una tanda de 50.000 celdas tarda **~41 s** (antes ~16 s):
  son **19 tandas seguidas, ~13 minutos** en los que **ninguna caja puede cerrar
  una venta ni nadie puede recibir mercadería** — esas operaciones quedan
  esperando el lock. La publicación de los asientos **no toma ese lock**: puede
  correr después, incluso con el sistema en uso.

- 🔴 **Cotización de la moneda secundaria, de la fecha EXACTA.** Las compañías de
  FORUM tienen `secondary_currency_id` (USD), y la copia de
  `aml_secondary_currency` que gana por orden del `addons_path` es la de
  `general_primate`, que busca la cotización con **la fecha exacta del asiento**
  —sin caer a la última anterior— y levanta `UserError` desde el `_post()`. O sea
  que **sin la cotización del día, la publicación no arranca**. El módulo lo
  valida antes de empezar y frena con la lista de fechas que faltan; en
  producción la carga el cron del BCU, pero hay que **verificarlo antes de la
  corrida**. El detalle de las dos copias del módulo está en `FINDINGS.md`.

- 🔴 **El camino ORM sale hacia el WMS. Riesgo de producción.**
  `integracion_wis` engancha el `write` de `product.product` y
  `product.template` y, si la comunicación está activa, hace **un request HTTP
  por producto**. El apply por ORM lo dispara por **dos vías**:

  1. `_run_fifo` escribe el `standard_price` del producto al consumir capas
     → `Product.write` → `enviarWS()`;
  2. mover stock reactiva pickings en espera → `_action_assign` →
     `insertarPedidos`.

  Se detectó en la copia porque las credenciales eran inválidas
  (`invalid_client`); **con credenciales válidas habría mandado datos de
  verdad**. Todos los caminos ORM del módulo corren con el guard
  `_avoid_wms=True` (y `skip_wms_integration`), **el camino SQL no lo dispara**,
  y el invariante 7 audita contra `product_wms_log`, `wis_sync_queue` y
  `wms_integracion_log` que no haya salido ni una fila. Aun así, para la corrida
  real conviene **desactivar la comunicación** del módulo desde su
  configuración: el guard es del código, la compuerta es de datos.

- **Fecha contable:** si `inventory_accounting_date` está vacía, los movimientos
  y los asientos llevan la fecha en que se aplica. La define el contador del
  cliente.

- **El apply y la publicación son reanudables.** Cancelar es un *pedido*: la
  tanda en curso termina y lo ya hecho queda. Reanudar retoma desde el puntero
  (la publicación recuenta los borradores pendientes, así que lo ya publicado no
  vuelve a pasar). Un choque de concurrencia reintenta la tanda hasta 3 veces, y
  un asiento que no publica se reintenta solo y queda en borrador con el motivo
  en el log, sin frenar la corrida.

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

Y lo que el **camino SQL** no replica, y por eso se deriva al ORM en vez de
aproximarlo:

- **Costeo que no sea FIFO** (AVCO, estándar). El SQL replica FIFO, que es lo que
  usan las 94 categorías del archivo; AVCO tiene además la corrección de
  redondeo del `standard_price` y no hay ni un caso en la base para verificarlo,
  así que esos productos van por `_apply_inventory`. Si en producción aparecen
  categorías AVCO, **conviene medir cuántas celdas son antes de la corrida**.
- **Capas negativas preexistentes**: las corrige el `_fifo_vacuum`, que crea
  capas de ajuste y sus asientos. No se replica.
- **Reservas y líneas pendientes** en la ubicación (`_free_reservation`).
- **Seguimiento por lote/serie** y pares con quants duplicados.

Tampoco se implementó, y queda como decisión del cliente: **agrupar los
asientos** (uno por producto o por categoría en vez de uno por capa). Bajaría el
tiempo de publicación, pero cambia lo que ve el contador.

## Checklist pre-producción

1. **Dump verificado** (ver el de clientes).
2. `python3 -c "import openpyxl"` en el entorno del servidor.
3. `shasum -a 256 forum_partner_import/data/ajuste_inventario_20260912.xlsx`
   contra la huella de arriba.
4. 🔴 **Tipo de cambio de la moneda secundaria cargado para la fecha EXACTA de
   los asientos.** No vale la del día anterior: la copia de
   `aml_secondary_currency` que corre exige coincidencia exacta. El módulo lo
   valida antes de publicar y frena, pero conviene verificarlo antes:

   ```sql
   SELECT name FROM res_currency_rate
    WHERE currency_id = (SELECT secondary_currency_id FROM res_company WHERE id = 1)
      AND name = CURRENT_DATE;   -- tiene que devolver una fila
   ```

5. 🔴 **Comunicación con el WMS desactivada** durante la corrida (la compuerta
   de `integracion_wis`, además del guard del código):

   ```sql
   SELECT comunicacion_activa FROM integracion_wis_integracion_wis;  -- false
   ```

6. **Cuentas y diario de stock en TODAS las categorías** de los productos del
   archivo, si van a valuar en tiempo real. Ojo: una propiedad puede existir con
   el valor **vacío**, y entonces el producto queda sin cuenta aunque la fila
   esté; la aplicación corta con `UserError` si pasa:

   ```sql
   SELECT count(*) FROM ir_property
    WHERE name = 'property_stock_valuation_account_id'
      AND (value_reference IS NULL OR value_reference NOT LIKE 'account.account,%');
   ```

7. Después de cargar el staging, revisar el log y el export: IDs no encontrados
   (en producción deberían ser 0), ubicaciones por compañía, no almacenables.
8. Confirmar con el contador la fecha contable y los asientos.
9. Mirar en el log de la primera tanda cuántos productos van por el ORM
   (`clasificación (N productos vía ORM)`): si en producción son muchos más que en
   la prueba, rediscutir antes de seguir. El widget muestra ritmo y ETA.
10. **Al terminar la aplicación, leer el informe de invariantes** en el batch
    (`Verificación`). Si dice *con violaciones*, **no publicar**: el detalle
    lista qué falló y con qué ejemplos.
11. **Publicar los asientos** (botón 4) y volver a leer el informe: ahí suman los
    invariantes de la publicación (nada en borrador, numeración sin huecos ni
    duplicados, suma del diario igual a la suma de las capas).
