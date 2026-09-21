"""Lee los artículos de Knowledge y arma la jerarquía.

Convención del manifest, pedida por el cliente y NO atada a una profundidad
fija: nivel 1 = Título, nivel 2 = Sección, nivel >= 3 = Artículo. Además se
guarda el path completo real, que es lo único que no miente cuando el árbol
tiene cinco niveles.
"""
import logging
import re
import unicodedata

_logger = logging.getLogger(__name__)

CAMPOS = [
    "id", "name", "parent_id", "sequence", "body", "is_article_item",
    "category", "active", "icon", "write_date", "create_date",
]

MAX_SLUG = 60

# Modos de nombre de archivo (y de subida):
#   mirror -> `NNN_slug_<id>` dentro del árbol de carpetas espejo
#   flat   -> `010-030-020_slug_<id>` todo en una carpeta, con la posición en el
#             árbol codificada en el nombre para que el orden ALFABÉTICO sea el
#             orden jerárquico.
MODOS = ("flat", "mirror")

# Los ordinales van de 10 en 10 para dejar lugar a intercalar a mano sin
# renumerar todo. Con 3 dígitos entran 99 hermanos por nivel; si alguna vez hay
# más, el ancho crece solo (ver `_ancho_prefijo`).
PASO_ORDEN = 10


def slug(texto, por_defecto="sin-titulo"):
    """Nombre de archivo seguro: sin tildes, sin signos, corto y estable."""
    if not texto:
        return por_defecto
    # NFKD separa la tilde de la letra; el encode la descarta.
    plano = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    plano = re.sub(r"[^A-Za-z0-9]+", "-", plano).strip("-").lower()
    plano = re.sub(r"-{2,}", "-", plano)
    return (plano[:MAX_SLUG].rstrip("-") or por_defecto)


class Articulo:
    """Un artículo con su lugar en el árbol."""

    def __init__(self, datos):
        self.id = datos["id"]
        self.nombre = (datos.get("name") or "").strip()
        self.parent_id = datos["parent_id"][0] if datos.get("parent_id") else None
        self.sequence = datos.get("sequence") or 0
        self.body = datos.get("body") or ""
        self.es_item = bool(datos.get("is_article_item"))
        self.category = datos.get("category") or ""
        self.icon = datos.get("icon") or ""
        self.hijos = []
        self.padre = None
        self.orden = 0          # posición entre hermanos, para el prefijo NNN_
        self.ruta_orden = []    # ordinales de todos los ancestros + el propio
        # Se completan al recorrer el árbol.
        self.nivel = 1
        self.path = []
        self.carpeta = ""
        self.archivo_pdf = ""
        self.archivo_html = ""

    @property
    def titulo(self):
        return self.nombre or "(sin título) %s" % self.id

    @property
    def tiene_contenido(self):
        """¿Vale la pena un PDF? Un artículo sin body ni hijos es una carpeta vacía."""
        return bool(re.sub(r"<[^>]+>|&nbsp;|\s", "", self.body))

    def __repr__(self):
        return "<Articulo %s %r>" % (self.id, self.titulo[:40])


def leer_articulos(rpc, root_id=None, incluir_privados=False, incluir_archivados=False,
                   limite=None):
    """Trae los artículos del alcance pedido y devuelve {id: Articulo}."""
    dominio = []
    if not incluir_archivados:
        dominio.append(("active", "=", True))
    else:
        dominio.append(("active", "in", [True, False]))
    if not incluir_privados:
        dominio.append(("category", "=", "workspace"))

    if root_id:
        # El subárbol se resuelve con `parent_path`, que es el materialized path
        # que ya mantiene Odoo: una sola consulta en vez de bajar nivel por nivel.
        raiz = rpc.execute("knowledge.article", "read", [root_id],
                           fields=["parent_path", "name"])
        if not raiz:
            raise RuntimeError("No existe el artículo raíz %s" % root_id)
        prefijo = raiz[0].get("parent_path") or ""
        _logger.info("Alcance: subárbol de %r (id %s, parent_path %s)",
                     raiz[0].get("name"), root_id, prefijo)
        dominio.append(("parent_path", "=like", "%s%%" % prefijo))

    ids = rpc.execute("knowledge.article", "search", dominio,
                      order="sequence, id")
    if limite:
        ids = ids[:limite]
    _logger.info("Artículos en alcance: %d", len(ids))
    filas = rpc.read_en_lotes("knowledge.article", ids, CAMPOS, tam_lote=40,
                              etiqueta="leyendo artículos")
    return {f["id"]: Articulo(f) for f in filas}


def _ancho_prefijo(raices):
    """Dígitos que necesita el ordinal más grande del árbol.

    Con 20 hermanos como máximo (medido en producción) alcanzan 3, pero el ancho
    se calcula igual: un nivel con más de 99 hermanos rompería el orden
    alfabético, que es justo lo único que el modo plano tiene que garantizar.
    """
    mayor = 0

    def bajar(nodos):
        nonlocal mayor
        mayor = max(mayor, len(nodos))
        for a in nodos:
            bajar(a.hijos)

    bajar(raices)
    return max(3, len("%d" % (mayor * PASO_ORDEN)))


def nombre_archivo(art, extension, modo="mirror", ancho=3, profundidad=1):
    """Nombre del archivo del artículo, según el modo.

    El `<id>` va siempre al final: es lo que garantiza que dos artículos con el
    mismo título no colisionen cuando caen todos en la misma carpeta.

    🔴 En `flat` el prefijo se RELLENA con ceros hasta la profundidad del árbol,
    y no es capricho: sin eso el orden alfabético pone al padre DESPUÉS de sus
    hijos, porque el separador de niveles `-` (0x2D) ordena antes que el `_`
    (0x5F) que abre el slug:

        160-010-080-010_configuracion-pos-manual_293   <- hijo
        160-010-080_metodos-de-pagos-manuales_265      <- padre, va después
        160-010_administracion-de-puntos-de-venta_140  <- abuelo, más después

    Con todos los nombres al mismo número de grupos, el `000` de los niveles que
    el artículo no usa ordena antes que cualquier posición real y el listado
    queda en el orden del árbol (padre y después sus hijos), que es lo único que
    este modo tiene que garantizar.
    """
    if modo == "flat":
        niveles = list(art.ruta_orden) + [0] * (profundidad - len(art.ruta_orden))
        prefijo = "-".join(("%0*d" % (ancho, o * PASO_ORDEN)) for o in niveles)
    else:
        prefijo = "%03d" % art.orden
    return "%s_%s_%d.%s" % (prefijo, slug(art.titulo), art.id, extension)


def armar_arbol(por_id, root_id=None, modo="mirror"):
    """Enlaza padres e hijos y completa nivel, path, carpeta y nombres.

    `modo` decide cómo se llaman los archivos (ver `nombre_archivo`).
    """
    for art in por_id.values():
        if art.parent_id and art.parent_id in por_id:
            padre = por_id[art.parent_id]
            padre.hijos.append(art)
            art.padre = padre

    raices = [a for a in por_id.values() if a.padre is None]
    if root_id and root_id in por_id:
        # Con --root-id, la raíz del export es ese artículo aunque tenga padre
        # fuera del alcance.
        raices = [por_id[root_id]]

    def recorrer(nodos, nivel, path, carpeta, orden_padre):
        nodos.sort(key=lambda a: (a.sequence, a.id))
        for i, art in enumerate(nodos, start=1):
            art.nivel = nivel
            art.orden = i
            art.ruta_orden = orden_padre + [i]
            art.path = path + [art.titulo]
            nombre_carpeta = "%03d_%s" % (i, slug(art.titulo))
            art.carpeta = "%s/%s" % (carpeta, nombre_carpeta) if carpeta else nombre_carpeta
            recorrer(art.hijos, nivel + 1, art.path, art.carpeta, art.ruta_orden)

    recorrer(raices, 1, [], "", [])

    # Los nombres se resuelven en una segunda pasada: el ancho del prefijo
    # depende del árbol entero, no se puede saber mientras se lo recorre.
    ancho = _ancho_prefijo(raices)
    todos = recorrido(raices)
    profundidad = max((a.nivel for a in todos), default=1)
    for art in todos:
        art.archivo_pdf = nombre_archivo(art, "pdf", modo, ancho, profundidad)
        art.archivo_html = nombre_archivo(art, "html", modo, ancho, profundidad)
    return raices


def recorrido(raices):
    """Los artículos en orden de árbol (padre antes que hijos)."""
    salida = []

    def bajar(nodos):
        for art in nodos:
            salida.append(art)
            bajar(art.hijos)

    bajar(raices)
    return salida


def etiquetas_jerarquia(art):
    """(Título, Sección, Artículo) según la convención del manifest."""
    path = art.path
    titulo = path[0] if len(path) >= 1 else ""
    seccion = path[1] if len(path) >= 2 else ""
    articulo = path[-1] if len(path) >= 3 else ""
    return titulo, seccion, articulo
