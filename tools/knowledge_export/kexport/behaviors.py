"""Convierte los *behaviors* del editor de Knowledge en HTML imprimible.

🔴 Esto no es un detalle: en el `body` que guarda Odoo, los bloques del editor
—video, archivo, plantilla, índice, link a artículo— son **divs vacíos o casi
vacíos** con la información metida en `data-behavior-props`, que es un JSON
url-encoded. Odoo los dibuja en el navegador con JavaScript. Un PDF hecho del
`body` crudo pierde todo eso y deja huecos.

Medido sobre `o17_support_forum` (253 artículos activos): 76 con bloque de
archivo, 74 con video, 74 con plantilla. Cero `<iframe>`: los videos NO están
como iframe.
"""
import json
import logging
import urllib.parse

_logger = logging.getLogger(__name__)

# Cómo se arma la URL pública de cada plataforma a partir del `videoId`.
PLATAFORMAS = {
    "youtube": "https://www.youtube.com/watch?v=%s",
    "vimeo": "https://vimeo.com/%s",
    "dailymotion": "https://www.dailymotion.com/video/%s",
    "youku": "https://v.youku.com/v_show/id_%s.html",
    "loom": "https://www.loom.com/share/%s",
    "drive": "https://drive.google.com/file/d/%s/view",
}


def leer_props(el):
    """Decodifica `data-behavior-props` (JSON url-encoded). {} si no hay o rompe."""
    crudo = el.get("data-behavior-props")
    if not crudo:
        return {}
    try:
        return json.loads(urllib.parse.unquote(crudo))
    except (ValueError, TypeError) as e:
        _logger.warning("data-behavior-props ilegible (%s): %s", e, crudo[:120])
        return {}


def _nuevo(soup, tag, clase=None, texto=None):
    el = soup.new_tag(tag)
    if clase:
        el["class"] = clase
    if texto is not None:
        el.string = texto
    return el


def _url_video(props):
    """URL pública del video a partir de las props del behavior."""
    video_id = props.get("videoId") or props.get("video_id")
    plataforma = (props.get("platform") or "").lower()
    if props.get("url"):
        return props["url"]
    if not video_id:
        return ""
    plantilla = PLATAFORMAS.get(plataforma)
    if not plantilla:
        _logger.warning("Plataforma de video desconocida: %r (id %s)", plataforma, video_id)
        return "%s:%s" % (plataforma or "video", video_id)
    return plantilla % video_id


def transformar(soup, base_url="", resolver_articulo=None):
    """Reemplaza in-place todos los behaviors de `soup`.

    `resolver_articulo(id)` devuelve el título del artículo destino, para que un
    link interno quede legible en papel. Puede ser None.

    Devuelve un dict con lo que hubo que resolver: `videos` (lista de URLs,
    puede haber varias por artículo), `archivos`, `avisos`.
    """
    resumen = {"videos": [], "archivos": [], "avisos": []}

    # --- Video: el div está VACÍO, todo sale de las props.
    for el in soup.select(".o_knowledge_behavior_type_video"):
        props = leer_props(el)
        url = _url_video(props)
        if url:
            resumen["videos"].append(url)
        caja = _nuevo(soup, "div", "kx-video")
        caja.append(_nuevo(soup, "span", "kx-video-icon", "🎬"))
        etiqueta = _nuevo(soup, "span", "kx-video-label", "Video: ")
        caja.append(etiqueta)
        if url:
            enlace = _nuevo(soup, "a", "kx-video-url", url)
            enlace["href"] = url
            caja.append(enlace)
        else:
            caja.append(_nuevo(soup, "span", "kx-missing", "(no se pudo resolver la URL)"))
            resumen["avisos"].append("video sin URL resoluble")
        el.replace_with(caja)

    # --- Archivo adjunto: a veces viene en las props (`fileData`) y a veces
    # sólo en el DOM interno. Se aceptan las dos formas.
    for el in soup.select(".o_knowledge_behavior_type_file"):
        props = leer_props(el).get("fileData") or {}
        nombre = props.get("name") or props.get("filename") or ""
        extension = props.get("extension") or ""
        url = props.get("url") or ""
        if not nombre:
            nodo = el.select_one(".o_knowledge_file_name")
            nombre = nodo.get_text(strip=True) if nodo else ""
        if not extension:
            nodo = el.select_one(".o_knowledge_file_extension")
            extension = nodo.get_text(strip=True) if nodo else ""
        if not url:
            nodo = el.select_one("a[href]")
            url = nodo.get("href", "") if nodo else ""
        if url.startswith("/") and base_url:
            url = base_url.rstrip("/") + url
        etiqueta = nombre or "(archivo sin nombre)"
        if extension:
            etiqueta = "%s (.%s)" % (etiqueta, extension)
        resumen["archivos"].append(etiqueta)
        caja = _nuevo(soup, "div", "kx-file")
        caja.append(_nuevo(soup, "span", "kx-file-icon", "📎"))
        caja.append(_nuevo(soup, "span", "kx-file-label", "Archivo adjunto: "))
        if url:
            enlace = _nuevo(soup, "a", "kx-file-url", etiqueta)
            enlace["href"] = url
            caja.append(enlace)
        else:
            caja.append(_nuevo(soup, "span", None, etiqueta))
        el.replace_with(caja)

    # --- Plantilla / portapapeles: el contenido real ya está en el DOM, dentro
    # de `.o_knowledge_content`. Se conserva ese contenido y se tira el marco.
    for el in soup.select(".o_knowledge_behavior_type_template"):
        contenido = el.select_one(".o_knowledge_content")
        caja = _nuevo(soup, "div", "kx-template")
        caja.append(_nuevo(soup, "div", "kx-template-label", "Plantilla"))
        if contenido:
            cuerpo = _nuevo(soup, "div", "kx-template-body")
            for hijo in list(contenido.contents):
                cuerpo.append(hijo.extract())
            caja.append(cuerpo)
        el.replace_with(caja)

    # --- Índice de artículos: ya trae un <ol> con links reales.
    for el in soup.select(".o_knowledge_behavior_type_articles_structure"):
        contenido = el.select_one(".o_knowledge_articles_structure_content")
        caja = _nuevo(soup, "div", "kx-index")
        caja.append(_nuevo(soup, "div", "kx-index-label", "Índice de artículos"))
        if contenido:
            for hijo in list(contenido.contents):
                caja.append(hijo.extract())
        el.replace_with(caja)

    # --- Link a otro artículo: queda como texto con el título, si se conoce.
    for el in soup.select(".o_knowledge_behavior_type_article"):
        props = leer_props(el)
        destino = props.get("article_id") or el.get("data-oe-nodeid")
        titulo = el.get_text(strip=True) or ""
        if resolver_articulo and destino:
            try:
                titulo = resolver_articulo(int(destino)) or titulo
            except (TypeError, ValueError):
                pass
        caja = _nuevo(soup, "span", "kx-article-link",
                      "📄 %s" % (titulo or "artículo %s" % destino))
        el.replace_with(caja)

    # --- Barras de herramientas del editor: no son contenido.
    for el in soup.select(".o_knowledge_toolbar, [data-oe-transient-content='true']"):
        el.decompose()

    return resumen


def absolutizar_links(soup, base_url):
    """Deja los `href` internos como URL absoluta, para que el PDF sea navegable."""
    if not base_url:
        return
    base = base_url.rstrip("/")
    for a in soup.select("a[href]"):
        href = a["href"]
        if href.startswith("/"):
            a["href"] = base + href
