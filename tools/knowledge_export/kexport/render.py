"""Arma el HTML final de cada artículo: breadcrumb, título, cuerpo y CSS."""
import html as html_mod
import logging

from bs4 import BeautifulSoup

from . import behaviors

_logger = logging.getLogger(__name__)

CSS = """
@page { size: A4; margin: 18mm 15mm 18mm 15mm;
        @bottom-center { content: counter(page) " / " counter(pages);
                         font: 9pt/1 "Helvetica Neue", Helvetica, Arial, sans-serif;
                         color: #888; } }
body { font: 11pt/1.55 "Helvetica Neue", Helvetica, Arial, sans-serif;
       color: #222; margin: 0; }
.kx-breadcrumb { font-size: 8.5pt; color: #777; border-bottom: 1px solid #ddd;
                 padding-bottom: 6px; margin-bottom: 14px; }
.kx-breadcrumb .sep { color: #bbb; padding: 0 4px; }
h1 { font-size: 20pt; margin: 0 0 4px 0; line-height: 1.25; }
.kx-meta { font-size: 8.5pt; color: #999; margin-bottom: 18px; }
h2 { font-size: 15pt; margin: 20px 0 6px; break-after: avoid; }
h3 { font-size: 12.5pt; margin: 16px 0 5px; break-after: avoid; }
p { margin: 0 0 8px; }
ul, ol { margin: 0 0 10px 0; padding-left: 22px; }
li { margin-bottom: 3px; }
a { color: #16607a; text-decoration: underline; word-break: break-word; }
img { max-width: 100%; height: auto; break-inside: avoid; }
figure { margin: 10px 0; break-inside: avoid; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 10pt;
        break-inside: avoid; }
th, td { border: 1px solid #bbb; padding: 5px 7px; vertical-align: top;
         text-align: left; }
th { background: #f2f2f2; font-weight: 600; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
blockquote { border-left: 3px solid #ddd; margin: 10px 0; padding: 2px 0 2px 12px;
             color: #555; }
pre, code { font-family: "SFMono-Regular", Menlo, Consolas, monospace; font-size: 9.5pt; }
pre { background: #f6f6f6; border: 1px solid #e3e3e3; padding: 8px;
      white-space: pre-wrap; word-wrap: break-word; break-inside: avoid; }
hr { border: 0; border-top: 1px solid #ddd; margin: 16px 0; }

/* Bloques del editor de Knowledge, reconstruidos para papel. */
.kx-video, .kx-file { border: 1px solid #cfd8dc; background: #f4f8fa;
                      border-radius: 4px; padding: 8px 10px; margin: 10px 0;
                      font-size: 10pt; break-inside: avoid; }
.kx-video-icon, .kx-file-icon { margin-right: 6px; }
.kx-video-label, .kx-file-label { font-weight: 600; }
.kx-template { border-left: 3px solid #b0bec5; padding-left: 10px; margin: 10px 0; }
.kx-template-label { font-size: 8.5pt; color: #90a4ae; text-transform: uppercase;
                     letter-spacing: .5px; margin-bottom: 4px; }
.kx-index { border: 1px dashed #cfd8dc; padding: 8px 10px; margin: 10px 0;
            break-inside: avoid; }
.kx-index-label { font-weight: 600; margin-bottom: 4px; }
.kx-article-link { color: #16607a; }
.kx-img-missing { border: 1px dashed #e57373; color: #c62828; background: #fdf3f3;
                  padding: 8px 10px; margin: 8px 0; font-size: 9.5pt; }
.kx-missing { color: #c62828; }
.kx-empty { color: #999; font-style: italic; }
"""

PLANTILLA = """<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><title>%(titulo)s</title>
<style>%(css)s</style></head>
<body>
<div class="kx-breadcrumb">%(breadcrumb)s</div>
<h1>%(h1)s</h1>
<div class="kx-meta">%(meta)s</div>
%(cuerpo)s
</body></html>
"""


def _breadcrumb(path):
    partes = [html_mod.escape(p) for p in path]
    return '<span class="sep">&gt;</span>'.join(partes) or "&nbsp;"


def _quitar_titulo_repetido(raiz, titulo):
    """Saca el encabezado inicial si repite el título del artículo.

    Medido sobre el subárbol exportado: 83 de 98 artículos arrancan con un
    `<h1>` que dice exactamente lo mismo que el nombre del artículo, así que sin
    esto el título sale DOS veces en casi todas las páginas. No se pierde nada:
    el título sigue como H1 del documento, con su breadcrumb.
    """
    objetivo = (titulo or "").strip().lower()
    if not objetivo:
        return False
    for nodo in raiz.find_all(True, recursive=False)[:3]:
        if nodo.name not in ("h1", "h2", "h3"):
            if nodo.get_text(strip=True):
                return False   # ya empezó el contenido de verdad
            continue
        if nodo.get_text(strip=True).lower() == objetivo:
            nodo.decompose()
            return True
        return False
    return False


def construir(art, resolutor_imagenes, base_url="", resolver_articulo=None,
              quitar_titulo_repetido=True):
    """HTML completo del artículo. Devuelve (html, resumen)."""
    soup = BeautifulSoup(art.body or "", "lxml")
    # `lxml` envuelve en <html><body>: se trabaja sobre lo que haya adentro.
    raiz = soup.body or soup
    titulo_deduplicado = False
    if quitar_titulo_repetido:
        titulo_deduplicado = _quitar_titulo_repetido(raiz, art.nombre)

    resumen_beh = behaviors.transformar(soup, base_url=base_url,
                                        resolver_articulo=resolver_articulo)
    resumen_img = resolutor_imagenes.embeber(soup, art.id)
    behaviors.absolutizar_links(soup, base_url)

    cuerpo = "".join(str(x) for x in raiz.contents).strip()
    if not cuerpo:
        cuerpo = '<p class="kx-empty">(Este artículo no tiene contenido propio.)</p>'

    icono = ("%s " % art.icon) if art.icon else ""
    meta = "ID Odoo %s &middot; nivel %s" % (art.id, art.nivel)
    if art.es_item:
        meta += " &middot; elemento de lista"

    documento = PLANTILLA % {
        "titulo": html_mod.escape(art.titulo),
        "css": CSS,
        "breadcrumb": _breadcrumb(art.path),
        "h1": html_mod.escape(icono + art.titulo),
        "meta": meta,
        "cuerpo": cuerpo,
    }
    resumen = {
        "videos": resumen_beh["videos"],
        "archivos": resumen_beh["archivos"],
        "avisos": resumen_beh["avisos"],
        "imagenes_ok": resumen_img["resueltas"],
        "imagenes_inline": resumen_img["inline"],
        "imagenes_fallidas": resumen_img["fallidas"],
        "detalle_fallidas": resumen_img["detalle_fallidas"],
        "titulo_deduplicado": titulo_deduplicado,
    }
    return documento, resumen
