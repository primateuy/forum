"""Sube PDFs, HTML y manifest al módulo Documentos, replicando la jerarquía.

🔴 El modelo de carpetas cambió: hasta la 17 eran `documents.folder`; desde la
18 las carpetas son `documents.document` con `type='folder'` y el padre en
`folder_id`. Verificado contra una base 19.0 real: la tabla `documents_folder`
no existe y hay 210 registros con `type='folder'`. Acá se detecta en vivo en vez
de asumir, porque el mismo script tiene que servir para las dos.

ACCESO POR ENLACE
Los documentos se dejan accesibles con el enlace (`access_via_link`) para que el
agente de soporte pueda pasarle el link a quien preguntó. Dos cosas que no son
obvias y que costaron encontrar:

- 🔴 **El link que copia Odoo no le sirve a un usuario externo.** `access_url`
  es `{base}/odoo/documents/<token>`, y `/odoo/...` es la ruta del webclient:
  `web/controllers/home.py:46-52` manda a `/web/login` a cualquiera que no tenga
  sesión. El link que hay que repartir es **`{base}/documents/<access_token>`**,
  que es público y redirige solo a los internos al backend.
- **«Descubrible» ya viene en Sí.** `is_access_via_link_hidden` es `False` por
  defecto; lo que está en `'none'` por defecto —y por eso el link no abre— es
  `access_via_link`. Se escriben los dos igual, explícitos.

Se aplica a los DOCUMENTOS y no a las carpetas a propósito: `access_via_link` en
una carpeta la vuelve enlazable entera, o sea un solo link que expone toda la
documentación. Los documentos que sube esta herramienta los marca esta
herramienta, uno por uno.
"""
import base64
import logging
import os

_logger = logging.getLogger(__name__)

# Valores de `documents.document.access_via_link`. `view` alcanza para descargar
# —`_from_access_token` sólo exige `!= 'none'`—; `edit` además deja a cualquiera
# con el link renombrar, modificar y borrar el documento.
ACCESOS = ("none", "view", "edit")

# El write de acceso se manda en tandas: son ids y dos campos, pero un write con
# miles de ids en un solo XML-RPC es una petición enorme por nada.
TANDA_ACCESO = 200


class Documentos:
    def __init__(self, rpc, on_conflict="replace", link_access="view", discoverable=True):
        self.rpc = rpc
        self.on_conflict = on_conflict
        if link_access not in ACCESOS:
            raise ValueError("link_access inválido: %r. Valores: %s"
                             % (link_access, ", ".join(ACCESOS)))
        self.link_access = link_access
        self.discoverable = discoverable
        self.modelo_carpeta = None      # 'documents.folder' o 'documents.document'
        self.soporta_acceso = False     # la 18+ tiene access_via_link; la 17 no
        self.creadas = 0
        self.reusadas = 0
        self.subidos = 0
        self.reemplazados = 0
        self.salteados = 0
        self.con_acceso = 0
        self._cache_carpetas = {}

    # ------------------------------------------------------------------
    def detectar(self):
        """Decide el modelo de carpetas mirando la base destino."""
        if self.rpc.tiene_modelo("documents.folder"):
            self.modelo_carpeta = "documents.folder"
        elif self.rpc.tiene_modelo("documents.document"):
            self.modelo_carpeta = "documents.document"
        else:
            raise RuntimeError(
                "El destino no tiene el módulo Documentos instalado "
                "(no existe ni documents.folder ni documents.document).")
        self.soporta_acceso = self.rpc.tiene_campo(
            "documents.document", "access_via_link")
        _logger.info("Documentos en destino: carpetas como %s (Odoo %s)",
                     self.modelo_carpeta, self.rpc.version)
        if self.soporta_acceso:
            _logger.info("Acceso por enlace: %s · descubrible: %s",
                         self.link_access, "sí" if self.discoverable else "no")
        else:
            _logger.warning(
                "El destino no tiene `access_via_link` (Odoo %s): los documentos se suben "
                "sin acceso por enlace y el agente de soporte no va a poder pasar links.",
                self.rpc.version)
        return self.modelo_carpeta

    # ------------------------------------------------------------------
    def _valores_acceso(self):
        """Los campos de acceso por enlace, o nada si el destino no los tiene."""
        if not self.soporta_acceso:
            return {}
        return {"access_via_link": self.link_access,
                "is_access_via_link_hidden": not self.discoverable}

    @property
    def carpetas_son_documentos(self):
        return self.modelo_carpeta == "documents.document"

    # ------------------------------------------------------------------
    def carpeta(self, nombre, padre_id=None):
        """Devuelve el id de la carpeta `nombre` bajo `padre_id`, creándola si falta."""
        clave = (nombre, padre_id)
        if clave in self._cache_carpetas:
            return self._cache_carpetas[clave]

        if self.carpetas_son_documentos:
            dominio = [("type", "=", "folder"), ("name", "=", nombre),
                       ("folder_id", "=", padre_id or False)]
            valores = {"name": nombre, "type": "folder", "folder_id": padre_id or False}
        else:
            dominio = [("name", "=", nombre), ("parent_folder_id", "=", padre_id or False)]
            valores = {"name": nombre, "parent_folder_id": padre_id or False}

        existentes = self.rpc.execute(self.modelo_carpeta, "search", dominio, limit=1)
        if existentes:
            carpeta_id = existentes[0]
            self.reusadas += 1
        else:
            carpeta_id = self.rpc.execute(self.modelo_carpeta, "create", valores)
            self.creadas += 1
            _logger.info("  carpeta creada: %s (id %s)", nombre, carpeta_id)
        self._cache_carpetas[clave] = carpeta_id
        return carpeta_id

    def ruta(self, partes, raiz_id=None):
        """Crea/resuelve una ruta completa de carpetas. Devuelve el id de la última."""
        actual = raiz_id
        for parte in partes:
            actual = self.carpeta(parte, actual)
        return actual

    def ruta_existente(self, partes, raiz_id=None):
        """Resuelve una ruta SIN crear nada. Devuelve el id, o None si falta un tramo.

        La necesita el `--dry-run`: `ruta()` crea las carpetas que no encuentra, y
        una corrida que promete no escribir nada no puede dejar carpetas nuevas en
        el Documentos del destino.
        """
        actual = raiz_id
        for parte in partes:
            if self.carpetas_son_documentos:
                dominio = [("type", "=", "folder"), ("name", "=", parte),
                           ("folder_id", "=", actual or False)]
            else:
                dominio = [("name", "=", parte), ("parent_folder_id", "=", actual or False)]
            encontradas = self.rpc.execute(self.modelo_carpeta, "search", dominio, limit=1)
            if not encontradas:
                return None
            actual = encontradas[0]
        return actual

    # ------------------------------------------------------------------
    def subir(self, ruta_archivo, nombre, carpeta_id, origen=""):
        """Sube un archivo a la carpeta. Idempotente según `on_conflict`."""
        with open(ruta_archivo, "rb") as fh:
            datos = base64.b64encode(fh.read()).decode()

        dominio = [("name", "=", nombre), ("folder_id", "=", carpeta_id)]
        if self.carpetas_son_documentos:
            dominio.append(("type", "=", "binary"))
        existentes = self.rpc.execute("documents.document", "search", dominio, limit=1)

        if existentes and self.on_conflict == "skip":
            self.salteados += 1
            return existentes[0], "skip"

        valores = {"name": nombre, "datas": datos, "folder_id": carpeta_id}
        if self.carpetas_son_documentos:
            valores["type"] = "binary"
        # El acceso va en el MISMO write/create que el archivo, no en una pasada
        # aparte: si se hiciera después, un corte a mitad de corrida dejaría
        # documentos subidos que nadie puede abrir con el link.
        acceso = self._valores_acceso()
        valores.update(acceso)
        if acceso:
            self.con_acceso += 1

        if existentes:
            doc_id = existentes[0]
            self.rpc.execute("documents.document", "write", [doc_id], valores)
            self.reemplazados += 1
            accion = "replace"
        else:
            doc_id = self.rpc.execute("documents.document", "create", valores)
            self.subidos += 1
            accion = "create"

        # Trazabilidad: `documents.document` de la 19 NO tiene campo description,
        # así que el origen se anota en el ir.attachment que cuelga del documento.
        if origen:
            self._anotar_origen(doc_id, origen)
        return doc_id, accion

    def _anotar_origen(self, doc_id, origen):
        try:
            filas = self.rpc.execute("documents.document", "read", [doc_id],
                                     fields=["attachment_id"])
            adjunto = filas[0].get("attachment_id") if filas else None
            if adjunto:
                self.rpc.execute("ir.attachment", "write", [adjunto[0]],
                                 {"description": origen})
        except Exception as e:  # noqa: BLE001 - la trazabilidad no puede tumbar la subida
            _logger.warning("No se pudo anotar el origen %s en el documento %s: %s",
                            origen, doc_id, e)

    # ------------------------------------------------------------------
    #  Corrección del acceso sobre lo ya subido
    # ------------------------------------------------------------------
    def documentos_bajo(self, carpeta_id, tope=12):
        """Los ids de todos los documentos binarios bajo esa carpeta y sus hijas.

        Se baja por niveles con un tope en vez de usar `child_of`: el dominio
        jerárquico depende de `parent_path`, y una jerarquía con un ciclo
        —que no debería existir pero existe si alguien la arma a mano— dejaría
        esto dando vueltas para siempre.
        """
        carpetas = [carpeta_id]
        frontera = [carpeta_id]
        for _nivel in range(tope):
            if not self.carpetas_son_documentos:
                break
            hijas = self.rpc.execute(
                "documents.document", "search",
                [("folder_id", "in", frontera), ("type", "=", "folder")])
            hijas = [h for h in hijas if h not in carpetas]
            if not hijas:
                break
            carpetas.extend(hijas)
            frontera = hijas

        dominio = [("folder_id", "in", carpetas)]
        if self.carpetas_son_documentos:
            dominio.append(("type", "=", "binary"))
        return self.rpc.execute("documents.document", "search", dominio)

    def fijar_acceso(self, doc_ids):
        """Escribe el acceso por enlace en documentos ya subidos. Devuelve cuántos."""
        acceso = self._valores_acceso()
        if not acceso or not doc_ids:
            return 0
        doc_ids = list(doc_ids)
        for inicio in range(0, len(doc_ids), TANDA_ACCESO):
            tanda = doc_ids[inicio:inicio + TANDA_ACCESO]
            self.rpc.execute("documents.document", "write", tanda, acceso)
            _logger.info("  acceso %d/%d", min(inicio + TANDA_ACCESO, len(doc_ids)), len(doc_ids))
        self.con_acceso += len(doc_ids)
        return len(doc_ids)

    def url_publica(self, doc_id):
        """El link que se le pasa a una persona de afuera.

        `{base}/documents/<access_token>` y NO `access_url`, que apunta a
        `/odoo/documents/...` —la ruta del webclient— y manda a la pantalla de
        login a cualquiera que no tenga sesión. Ver el encabezado del módulo.
        """
        filas = self.rpc.execute("documents.document", "read", [doc_id],
                                 fields=["access_token"])
        token = (filas[0].get("access_token") if filas else "") or ""
        return "%s/documents/%s" % (self.rpc.url, token) if token else ""

    # ------------------------------------------------------------------
    def resumen(self):
        texto = ("carpetas: %d creadas, %d reusadas | documentos: %d nuevos, "
                 "%d reemplazados, %d salteados"
                 % (self.creadas, self.reusadas, self.subidos,
                    self.reemplazados, self.salteados))
        if self.soporta_acceso:
            texto += " | acceso por enlace (%s) en %d" % (self.link_access, self.con_acceso)
        return texto
