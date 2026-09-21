# Exportación de Knowledge de FORUM a PDF + Documentos de Primate

Herramienta repetible, **standalone** (no es un módulo de Odoo), que:

1. lee los artículos de Conocimiento (`knowledge.article`) de FORUM por XML-RPC;
2. genera **un PDF y un HTML por artículo**, con título, formato, imágenes,
   tablas, listas y links;
3. arma un **`manifest.csv`** con la jerarquía y los metadatos;
4. sube PDFs y manifest al módulo **Documentos** de Primate replicando la
   jerarquía en carpetas, de forma **idempotente**.

El HTML se guarda aparte a propósito: es el insumo del proceso posterior.

---

## Instalación

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

WeasyPrint necesita además librerías **del sistema**:

```bash
# macOS
brew install pango
# Debian/Ubuntu
sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0
```

> 🔴 En macOS WeasyPrint carga esas librerías con `dlopen` y **no mira
> `/opt/homebrew/lib`** salvo que `DYLD_FALLBACK_LIBRARY_PATH` lo incluya. El
> script se re-ejecuta solo una vez con la variable puesta, así que no hay que
> hacer nada; si lo importás desde otro lado, acordate. Si WeasyPrint no carga,
> se usa **wkhtmltopdf** automáticamente (si está en el PATH).

## Configuración

```bash
cp config.example.json config.json   # ningún config*.json va al repo
```

La herramienta lee de **una** base y escribe en **otra**, las dos configurables,
así que conviene tener **un archivo por combinación de ambientes** y elegirlo con
`--config`:

| archivo | origen → destino |
|---|---|
| `config.support-to-test.json` | `o17_support_forum` → base de prueba |
| `config.prod-to-staging.json` | Forum **producción** → `o19_primate_staging` |
| `config.prod-to-prod.json` | Forum **producción** → Primate **producción** |

```bash
python3 export_knowledge.py --config config.prod-to-staging.json
```

El `.gitignore` deja fuera **todos** los `config*.json` menos el `.example`.

| clave | qué es |
|---|---|
| `origen.url / db / username / password` | Odoo de FORUM, de donde se lee |
| `origen.root_id` | artículo raíz por defecto (`null` = todo el alcance) |
| `destino.url / db / username / password` | Odoo de Primate, donde se sube |
| `destino.raiz` / `destino.ambiente` | carpetas raíz en Documentos (`Forum` / `Producción`) |
| `destino.upload_mode` | `flat` (default) o `mirror`; lo pisa `--upload-mode` |

En `password` conviene una **API key** (Ajustes → Mi perfil → Seguridad de la
cuenta), no la contraseña.

La `url` puede ir con o sin esquema: si falta, se asume `https://`.

> **Destinos en odoo.sh** — el `db` no es el nombre visible del branch, sino el
> **nombre técnico de la base, que sale del subdominio de la URL del build**.
> Para `https://primateuy-19-0-staging-12082026-1036-38416367.dev.odoo.com` la
> base es `primateuy-19-0-staging-12082026-1036-38416367`, no
> `19.0.Staging_12082026_1036`. Con el nombre equivocado la autenticación falla
> con un `Fault 1` cuyo traceback termina en `registry.py`, que no dice «esa
> base no existe» por ningún lado.

El usuario del destino necesita poder crear `documents.document` y escribir
`ir.attachment` (para la trazabilidad). **No** necesita leer `ir.model`, y no
hace falta dárselo.

## Uso

```bash
python3 export_knowledge.py --dry-run          # árbol y conteos, no escribe nada
python3 export_knowledge.py --skip-upload      # exporta a out/, sin subir
python3 export_knowledge.py --only-upload      # sube lo ya generado
python3 export_knowledge.py                    # exporta y sube
python3 export_knowledge.py --root-id 87       # sólo ese subárbol
```

| flag | qué hace |
|---|---|
| `--config RUTA` | qué configuración usar (default: `config.json` en esta carpeta) |
| `--yes` / `-y` | no pedir confirmación de ambientes (corridas desatendidas) |
| `--root-id N` | exportar sólo el subárbol de ese artículo |
| `--dry-run` | listar el árbol y contar artículos/imágenes/videos, sin generar |
| `--skip-upload` / `--only-upload` | separar las dos mitades |
| `--limit N` | tope de artículos, para probar. **Corta la lista antes de armar el árbol**, así que la jerarquía que se ve con `--limit` está recortada: sirve para probar el circuito, no para mirar la estructura |
| `--include-private` / `--include-archived` | ampliar el alcance |
| `--include-items` | PDF propio también para los `is_article_item` |
| `--upload-html` | subir también los HTML |
| `--upload-mode flat\|mirror` | cómo quedan los PDFs en Documentos (default `flat`) |
| `--on-conflict skip\|replace` | qué hacer si el documento ya existe (default `replace`) |
| `--pdf-engine auto\|weasyprint\|wkhtmltopdf` | forzar motor |
| `--keep-duplicate-title` | no quitar el encabezado que repite el título |
| `--no-http-images` | no bajar por HTTP las imágenes que no estén en `ir.attachment` |

## Modo de subida: `flat` (default) y `mirror`

Se elige con `--upload-mode` o con `destino.upload_mode` en la configuración; la
CLI pisa al archivo.

**`flat`** — todos los PDFs y el manifest **sueltos** dentro de
`<raiz>/<ambiente>`, sin subcarpetas. Es lo que pidió el equipo funcional: la
jerarquía ya está en el manifest y las carpetas espejo les estorbaban para
revisar y reorganizar. La posición en el árbol viaja en el **nombre del
archivo**, de modo que **el orden alfabético es el orden jerárquico**:

```
160-000-000-000-000_punto-de-venta_139.pdf
160-010-000-000-000_administracion-de-puntos-de-venta_140.pdf
160-010-010-000-000_definiciones-para-una-nueva-sucursal_243.pdf
...
160-010-080-000-000_metodos-de-pagos-manuales_265.pdf
160-010-080-010-000_configuracion-pos-manual_293.pdf
```

Un grupo por nivel, de 10 en 10 para poder intercalar a mano sin renumerar todo,
y el `<id>` al final para que dos artículos con el mismo título no choquen.

> 🔴 **El relleno con `000` no es decorativo.** Con prefijos de largo variable el
> orden alfabético pone al padre **después** de sus hijos, porque el separador de
> niveles `-` (0x2D) ordena antes que el `_` (0x5F) que abre el slug:
> `160-010-080-010_hijo` < `160-010-080_padre` < `160-010_abuelo`. Rellenando
> todos los nombres a la misma cantidad de grupos, el `000` de los niveles sin
> usar ordena primero y el listado queda en orden de árbol.

Antes de subir se verifica que no haya dos archivos con el mismo nombre: en
`flat` comparten carpeta, así que un nombre repetido sería un pisón silencioso.

**`mirror`** — el árbol de carpetas espejo, con `NNN_slug_<id>.pdf` dentro de
cada una. Queda por si alguna vez sirve.

El modo afecta **el nombre de los archivos**, así que la exportación y la subida
tienen que correrse con el mismo: si exportás en `mirror` y subís en `flat`, los
archivos caen todos juntos pero sin el prefijo que los ordena.

## Confirmación de ambientes

Toda corrida que **no** sea `--dry-run` arranca mostrando a qué se conecta y
pide confirmación:

```
==============================================================================
  CONFIGURACIÓN: config.prod-to-prod.json
------------------------------------------------------------------------------
  ORIGEN (se LEE)      https://forum.example.com
                      base forum_prod · usuario tecnico@primate.uy
                      alcance: subárbol del artículo 87
  DESTINO (se ESCRIBE) https://documentos.primate.uy
                      base primate_prod · usuario tecnico@primate.uy
                      carpeta Forum / Producción · conflictos: replace
------------------------------------------------------------------------------
  ⚠️  EL DESTINO PARECE PRODUCCIÓN: se va a ESCRIBIR en ... (base primate_prod)
  ⚠️  Los documentos que ya existan con el mismo nombre se REEMPLAZAN
==============================================================================
  ¿Continuar? (y/N)
```

Si la URL o el nombre de base del destino contienen `prod`, sale la advertencia
explícita. `--yes` saltea la pregunta; sin terminal interactiva y sin `--yes` la
corrida **se corta**, en vez de seguir a ciegas.

## Salida

```
out/forum_knowledge/
├── pdf/    <árbol espejo de la jerarquía>/NNN_slug_<id>.pdf
├── html/   <mismo árbol>/NNN_slug_<id>.html
├── manifest.csv
└── export.log
```

El nombre de los archivos depende del **modo de subida** (ver arriba): con
`mirror` es `NNN_slug_<id>` y con `flat`, `NNN-NNN-...-NNN_slug_<id>`. En los dos
casos el prefijo respeta el `sequence` de Odoo, así el orden se mantiene en
cualquier explorador de archivos. El árbol de carpetas local se arma siempre,
sea cual sea el modo.

### manifest.csv

`Título | Sección | Artículo | Path completo | ID Odoo | Parent ID | Secuencia |
Archivo PDF | Archivo HTML | Links de video | Ruta en Documentos |
Imagen irrecuperable`

Separador `;`, UTF-8 con BOM (para que Excel no rompa las tildes). Lleva **una
fila por artículo del alcance**, incluidos los que no generan PDF: el proceso
posterior necesita ver los nodos intermedios para armar la estructura.

Convención: **nivel 1 = Título, nivel 2 = Sección, nivel ≥3 = Artículo**. Como
la profundidad real varía (medido: hasta 5 niveles), el dato que no miente es
`Path completo`.

---

## Lo que hay que saber antes de tocar esto

### 🔴 Los bloques del editor no están en el `body`

En Knowledge, los videos, archivos, plantillas e índices son *behaviors*: divs
vacíos con la información en `data-behavior-props`, que es **JSON
url-encoded**. Odoo los dibuja en el navegador con JavaScript. Un PDF hecho del
`body` crudo los pierde y deja huecos.

Medido sobre `o17_support_forum` (253 artículos activos): 76 con bloque de
archivo, 74 con video, 74 con plantilla, y **cero `<iframe>`** — los videos NO
están como iframe. `kexport/behaviors.py` decodifica las props y reconstruye
cada bloque:

| behavior | queda como |
|---|---|
| `video` | `🎬 Video: <URL>` en un recuadro, clickeable, y la URL al manifest |
| `file` | `📎 Archivo adjunto: <nombre> (.ext)` con link absoluto |
| `template` | el contenido de la plantilla, con su etiqueta |
| `articles_structure` | el índice, que ya viene como `<ol>` con links |
| `article` | el título del artículo destino |

Los videos **no se descargan**, por diseño.

### Imágenes

Se resuelven en este orden: `ir.attachment` por RPC → descarga HTTP. Están
cubiertas las cuatro formas que aparecen en los `body` (`/web/image/<id>`,
`/web/image/<id>-<hash>/nombre.png?access_token=…`, `/web/content/<id>`,
`/web/image/<modelo>/<id>/<campo>`), las que ya vienen en base64, y las que son
**URL absoluta a otro Odoo** (25 de 313 en el subárbol exportado, en 3 hosts).
Las que no se pueden resolver dejan un **placeholder visible** y una línea en el
log: una imagen que falta en silencio es peor que una que se ve rota.

#### 🔴 Hay que leer de PRODUCCIÓN (o de un dump CON filestore)

`o17_support_forum` **no tiene los archivos de los adjuntos de Knowledge**: de
200 adjuntos muestreados, **0** tienen su archivo en el filestore. La base trae
las filas de `ir_attachment` con su `store_fname` y su `file_size`, pero el
binario no está, así que `datas` vuelve vacío por RPC y la descarga por HTTP
devuelve 500. Resultado: la mayoría de las imágenes sale con **placeholder**.

**No es un problema de la herramienta** — se verificó resolviendo las cuatro
formas de URL contra un adjunto que sí tiene archivo (id 23): 4 de 4 a data URI.

Para la corrida que vale, el origen tiene que ser **producción de Forum**, o un
dump restaurado **junto con su filestore**. Si el export sale con muchos
placeholders, lo primero a mirar es eso, no el código:

```sql
-- Tiene que devolver un número parecido al total, no cero.
SELECT count(*) FROM ir_attachment
 WHERE res_model = 'knowledge.article' AND store_fname IS NOT NULL;
```
y después comprobar que esos `store_fname` existan en el filestore de la base.

#### Imágenes irrecuperables

Las pegadas desde Word (`file:///C:/Users/…`) apuntan al disco de quien escribió
el artículo: no existen en ninguna base y **ninguna corrida contra producción
las va a traer**. Los artículos que las tienen quedan marcados en la columna
**`Imagen irrecuperable`** del manifest (`N: <url> | <url>`), para que en la fase
siguiente se sepa cuáles pedir de vuelta o revisar a mano. En el subárbol
exportado son 4, en 3 artículos.

### `is_article_item`

Por defecto **no** generan PDF propio: en Odoo son filas de una lista que el
artículo padre ya muestra en su cuerpo. Igual aparecen en el manifest. Se puede
cambiar con `--include-items`.

### Título repetido

83 de 98 artículos arrancan con un `<h1>` que dice exactamente lo mismo que el
nombre del artículo, así que sin dedupe el título sale **dos veces** en casi
todas las páginas. Se quita por defecto; `--keep-duplicate-title` lo deja.

### 🔴 El modelo de carpetas de Documentos cambió en la 18

Hasta la 17 las carpetas eran `documents.folder`. Desde la 18 son
`documents.document` con `type='folder'` y el padre en `folder_id` — verificado
contra una base 19.0 real: la tabla `documents_folder` **no existe**. El script
lo **detecta en vivo** (`kexport/upload.py`) en vez de asumir, así sirve para
las dos.

`documents.document` de la 19 tampoco tiene campo `description`, así que la
trazabilidad del origen se anota en el `ir.attachment` del documento:
`forum:knowledge.article:<id>`.

### Idempotencia

Re-ejecutar no duplica: se busca por nombre dentro de la carpeta destino y se
aplica `--on-conflict` (`replace` por defecto, `skip` disponible). Verificado:
segunda corrida = 0 carpetas creadas, 100 reusadas, 0 documentos nuevos.

---

## Verificado

Contra `o17_support_forum` (origen) y una base Odoo 19 con Documentos (destino):

| control | resultado |
|---|---|
| `--dry-run` | 100 artículos, 98 con contenido, profundidad máxima 5 |
| exportación | 98 PDFs en ~12 s, todos con WeasyPrint, 0 caídas al respaldo |
| PDFs revisados a mano | imágenes, tablas, listas, links, breadcrumb y paginado correctos |
| behaviors | video y archivo reconstruidos; URL del video en el manifest |
| manifest | 100 filas, 1 por artículo, sin huecos de Título ni de ID |
| subida | 100 carpetas espejo + 99 documentos |
| re-subida | 0 duplicados (`replace` y `skip` probados) |

**Pendiente de probar contra el destino real**: la corrida se hizo contra una
base Odoo 19 de prueba, no contra la instancia de Primate.

---

## Checklist de la corrida real

En este orden, sin saltear pasos. Cada uno se mira antes de pasar al siguiente.

1. **Origen correcto.** Producción de Forum, o un dump restaurado **con su
   filestore** (ver arriba). Contra `o17_support_forum` las imágenes salen con
   placeholder y el resultado no sirve para publicar.

2. **Dry-run completo**, sin `--root-id`, para ver el árbol entero (~253
   artículos entre workspace y privados; 175 de workspace):

   ```bash
   python3 export_knowledge.py --config config.prod-to-staging.json --dry-run
   ```

   Revisar: cantidad de artículos, cuántos tienen contenido, profundidad, y los
   conteos de imágenes, videos y archivos.

3. **Export completo**, todavía sin subir:

   ```bash
   python3 export_knowledge.py --config config.prod-to-staging.json --skip-upload
   ```

   Al terminar, mirar el resumen: **cuántas imágenes quedaron sin resolver**. Si
   son muchas, parar y revisar el filestore del origen antes de seguir.

4. **Validar el manifest**: una fila por artículo, sin huecos en `Título` ni en
   `ID Odoo`, los videos detectados, y la columna `Imagen irrecuperable` para
   saber qué artículos hay que revisar a mano.

5. **Revisar PDFs a mano**: al menos 5 variados (uno con tabla, uno con muchas
   imágenes, uno con video, uno de nivel profundo, uno hoja).

6. **Subir a staging de Primate primero**:

   ```bash
   python3 export_knowledge.py --config config.prod-to-staging.json --only-upload
   ```

   Abrir Documentos y comprobar la estructura de carpetas. Después **re-ejecutar
   el mismo comando** y confirmar que el resumen dice `0 nuevos` y que no
   aparecieron duplicados.

7. **Recién entonces producción**, con su propia configuración:

   ```bash
   python3 export_knowledge.py --config config.prod-to-prod.json --only-upload
   ```

   La herramienta va a mostrar la advertencia de destino productivo y pedir
   confirmación. Leer el resumen antes de contestar que sí.
