"""Resuelve las imágenes del `body` y las embebe como data URI.

Los `body` de knowledge.article referencian los adjuntos por URL
(`/web/image/<id>`, `/web/content/<id>`, con o sin nombre y parámetros). Un PDF
generado fuera del servidor no puede seguir esas URLs: hay que traer el binario
por RPC (`ir.attachment.datas`) y meterlo en el HTML.
"""
import base64
import logging
import re
from urllib.parse import urljoin

import requests

_logger = logging.getLogger(__name__)

# /web/image/123, /web/image/123-abcdef/nombre.png, /web/content/123?download=true,
# y la forma con modelo: /web/image/ir.attachment/123/datas
RE_ADJUNTO = re.compile(
    r"^/web/(?:image|content)/"
    r"(?:(?P<modelo>[a-z_.]+)/(?P<res_id>\d+)/(?P<campo>[a-z_]+)"
    r"|(?P<id>\d+)(?:-[0-9a-f]+)?)",
    re.IGNORECASE)

MIME_POR_DEFECTO = "image/png"

# Tope por imagen: una captura de pantalla pesa cientos de KB; varios MB en un
# `src` es casi seguro un archivo que no corresponde meter en el PDF.
MAX_BYTES = 12 * 1024 * 1024
TIMEOUT_HTTP = 20


class ResolutorImagenes:
    """Trae adjuntos por RPC y los cachea: la misma imagen se repite entre artículos."""

    def __init__(self, rpc, base_url="", permitir_http=True):
        self.rpc = rpc
        self.base_url = (base_url or "").rstrip("/")
        self.permitir_http = permitir_http
        self._cache = {}
        self._sesion = requests.Session()
        self.resueltas = 0
        self.fallidas = 0
        self.inline = 0
        self.por_http = 0

    # ------------------------------------------------------------------
    def _datos_adjunto(self, attachment_id):
        """(datas_base64, mimetype) del adjunto, o (None, None)."""
        if attachment_id in self._cache:
            return self._cache[attachment_id]
        try:
            filas = self.rpc.execute(
                "ir.attachment", "read", [attachment_id], fields=["datas", "mimetype"])
        except Exception as e:  # noqa: BLE001 - cualquier fallo deja placeholder
            _logger.warning("No se pudo leer ir.attachment %s: %s", attachment_id, e)
            filas = []
        if filas and filas[0].get("datas"):
            valor = (filas[0]["datas"], filas[0].get("mimetype") or MIME_POR_DEFECTO)
        else:
            valor = (None, None)
        self._cache[attachment_id] = valor
        return valor

    def _datos_campo(self, modelo, res_id, campo):
        """(base64, mimetype) de un campo binario cualquiera, o (None, None).

        La forma `/web/image/<modelo>/<id>/<campo>` no siempre apunta a un
        ir.attachment: también aparece con `knowledge.article/<id>/cover_image`
        o con campos de producto. Se lee el campo directo en vez de descartarlo.
        """
        clave = (modelo, res_id, campo)
        if clave in self._cache:
            return self._cache[clave]
        try:
            filas = self.rpc.execute(modelo, "read", [res_id], fields=[campo])
        except Exception as e:  # noqa: BLE001
            _logger.warning("No se pudo leer %s.%s de %s: %s", modelo, campo, res_id, e)
            filas = []
        datos = filas[0].get(campo) if filas else None
        valor = (datos, MIME_POR_DEFECTO) if datos else (None, None)
        self._cache[clave] = valor
        return valor

    def _descargar(self, url):
        """(base64, mimetype) bajando la imagen por HTTP, o (None, None).

        Hace falta de verdad: parte de los `body` traen las capturas como URL
        ABSOLUTA a otro Odoo (medido: 25 de 313 en el subárbol exportado, en 3
        hosts distintos). Esas no están en `ir.attachment` de esta base y por
        RPC no hay forma de traerlas.
        """
        if not self.permitir_http:
            return None, None
        if url in self._cache:
            return self._cache[url]
        valor = (None, None)
        try:
            r = self._sesion.get(url, timeout=TIMEOUT_HTTP, stream=True)
            if r.status_code == 200:
                contenido = r.raw.read(MAX_BYTES + 1, decode_content=True)
                if len(contenido) > MAX_BYTES:
                    _logger.warning("Imagen demasiado grande, se omite: %s", url)
                elif contenido:
                    mimetype = (r.headers.get("Content-Type") or MIME_POR_DEFECTO).split(";")[0]
                    valor = (base64.b64encode(contenido).decode(), mimetype)
            else:
                _logger.warning("HTTP %s al bajar %s", r.status_code, url)
        except requests.RequestException as e:
            _logger.warning("No se pudo bajar %s: %s", url, e)
        self._cache[url] = valor
        return valor

    def _resolver_src(self, src):
        """(base64, mimetype) detrás de un `src`, o (None, None).

        Orden: adjunto por RPC (lo más fiel y sin red) y, si no sale, HTTP. Las
        rutas relativas se resuelven contra la URL del origen conservando el
        `access_token`, que es lo que autoriza la descarga.
        """
        if src.startswith(("http://", "https://")):
            return self._descargar(src)
        if src.startswith("file://"):
            # Pegado desde Word: apunta al disco de quien escribió el artículo.
            return None, None

        m = RE_ADJUNTO.match(src)
        if m:
            if m.group("id"):
                datos = self._datos_adjunto(int(m.group("id")))
            else:
                modelo = (m.group("modelo") or "").lower()
                res_id, campo = int(m.group("res_id")), m.group("campo")
                datos = (self._datos_adjunto(res_id) if modelo == "ir.attachment"
                         else self._datos_campo(modelo, res_id, campo))
            if datos[0]:
                return datos

        if src.startswith("/") and self.base_url:
            return self._descargar(urljoin(self.base_url + "/", src.lstrip("/")))
        return None, None

    # ------------------------------------------------------------------
    def embeber(self, soup, articulo_id):
        """Reemplaza los `src` de `soup` por data URIs. Devuelve un resumen."""
        resumen = {"resueltas": 0, "inline": 0, "fallidas": 0, "detalle_fallidas": []}
        for img in soup.select("img[src]"):
            src = (img.get("src") or "").strip()
            if not src:
                continue
            if src.startswith("data:"):
                # Ya viene embebida: no hay nada que traer.
                resumen["inline"] += 1
                self.inline += 1
                continue
            datas, mimetype = self._resolver_src(src)
            if datas:
                img["src"] = "data:%s;base64,%s" % (mimetype or MIME_POR_DEFECTO, datas)
                resumen["resueltas"] += 1
                self.resueltas += 1
                if src.startswith(("http://", "https://")):
                    self.por_http += 1
                continue

            # No se pudo: placeholder VISIBLE. Una imagen que falta en silencio
            # es peor que una que se ve rota, porque nadie la busca después.
            resumen["fallidas"] += 1
            resumen["detalle_fallidas"].append(src)
            self.fallidas += 1
            _logger.warning("Artículo %s: no se pudo resolver la imagen %s", articulo_id, src)
            marca = soup.new_tag("div")
            marca["class"] = "kx-img-missing"
            marca.string = "🖼️ Imagen no disponible en la exportación: %s" % src
            img.replace_with(marca)
        return resumen
