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
cp config.example.json config.json   # config.json NO va al repo
```

| clave | qué es |
|---|---|
| `origen.url / db / username / password` | Odoo de FORUM, de donde se lee |
| `origen.root_id` | artículo raíz por defecto (`null` = todo el alcance) |
| `destino.url / db / username / password` | Odoo de Primate, donde se sube |
| `destino.raiz` / `destino.ambiente` | carpetas raíz en Documentos (`Forum` / `Producción`) |

En `password` conviene una **API key** (Ajustes → Mi perfil → Seguridad de la
cuenta), no la contraseña.

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
| `--root-id N` | exportar sólo el subárbol de ese artículo |
| `--dry-run` | listar el árbol y contar artículos/imágenes/videos, sin generar |
| `--skip-upload` / `--only-upload` | separar las dos mitades |
| `--limit N` | tope de artículos, para probar. **Corta la lista antes de armar el árbol**, así que la jerarquía que se ve con `--limit` está recortada: sirve para probar el circuito, no para mirar la estructura |
| `--include-private` / `--include-archived` | ampliar el alcance |
| `--include-items` | PDF propio también para los `is_article_item` |
| `--upload-html` | subir también los HTML |
| `--on-conflict skip\|replace` | qué hacer si el documento ya existe (default `replace`) |
| `--pdf-engine auto\|weasyprint\|wkhtmltopdf` | forzar motor |
| `--keep-duplicate-title` | no quitar el encabezado que repite el título |
| `--no-http-images` | no bajar por HTTP las imágenes que no estén en `ir.attachment` |

## Salida

```
out/forum_knowledge/
├── pdf/    <árbol espejo de la jerarquía>/NNN_slug_<id>.pdf
├── html/   <mismo árbol>/NNN_slug_<id>.html
├── manifest.csv
└── export.log
```

El prefijo `NNN_` respeta el `sequence` de Odoo, así el orden dentro de cada
carpeta se mantiene en cualquier explorador de archivos.

### manifest.csv

`Título | Sección | Artículo | Path completo | ID Odoo | Parent ID | Secuencia |
Archivo PDF | Archivo HTML | Links de video | Ruta en Documentos`

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

Las pegadas desde Word (`file:///C:/Users/…`) son irrecuperables por definición.

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
base Odoo 19 de prueba, no contra la instancia de Primate. Antes de apuntar a
producción, correr con `--limit 5` y revisar.
