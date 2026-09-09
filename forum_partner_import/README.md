# Importación masiva de clientes FORUM

Carga ~646.000 clientes y sus puntos de lealtad desde un CSV incluido en el
módulo, usando SQL directo por tandas para no tumbar el servidor.

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

1. **Contactos → Importación FORUM → Crear.**
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
