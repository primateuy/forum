"""Sube PDFs, HTML y manifest al módulo Documentos, replicando la jerarquía.

🔴 El modelo de carpetas cambió: hasta la 17 eran `documents.folder`; desde la
18 las carpetas son `documents.document` con `type='folder'` y el padre en
`folder_id`. Verificado contra una base 19.0 real: la tabla `documents_folder`
no existe y hay 210 registros con `type='folder'`. Acá se detecta en vivo en vez
de asumir, porque el mismo script tiene que servir para las dos.
"""
import base64
import logging
import os

_logger = logging.getLogger(__name__)


class Documentos:
    def __init__(self, rpc, on_conflict="replace"):
        self.rpc = rpc
        self.on_conflict = on_conflict
        self.modelo_carpeta = None      # 'documents.folder' o 'documents.document'
        self.creadas = 0
        self.reusadas = 0
        self.subidos = 0
        self.reemplazados = 0
        self.salteados = 0
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
        _logger.info("Documentos en destino: carpetas como %s (Odoo %s)",
                     self.modelo_carpeta, self.rpc.version)
        return self.modelo_carpeta

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
    def resumen(self):
        return ("carpetas: %d creadas, %d reusadas | documentos: %d nuevos, "
                "%d reemplazados, %d salteados"
                % (self.creadas, self.reusadas, self.subidos,
                   self.reemplazados, self.salteados))
