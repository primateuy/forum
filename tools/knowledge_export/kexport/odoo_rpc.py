"""Cliente XML-RPC con reintentos, lectura en lotes y detección de versión.

Todo el acceso a las dos bases (Forum origen, Primate destino) pasa por acá.
"""
import logging
import re
import socket
import ssl
import time
import xmlrpc.client

import certifi

_logger = logging.getLogger(__name__)

# Errores que SÍ vale la pena reintentar: la base puede estar reiniciando, la
# red cortarse, o el worker devolver un 5xx puntual. Un XML-RPC Fault (dominio
# mal escrito, campo inexistente, AccessError) no se reintenta: reintentarlo es
# perder tiempo y ensuciar el log con el mismo error N veces.
REINTENTABLES = (socket.error, xmlrpc.client.ProtocolError, ConnectionError, OSError)


class OdooRPC:
    """Conexión a una base de Odoo por XML-RPC."""

    def __init__(self, url, db, username, password, reintentos=4, espera_base=2.0):
        self.url = self._normalizar_url(url)
        self.db = db
        self.username = username
        self.password = password
        self.reintentos = reintentos
        self.espera_base = espera_base
        self.uid = None
        # 🔴 `xmlrpc.client` usa el contexto SSL por defecto de la stdlib, y en el
        # Python del framework de macOS ese contexto NO trae CA bundle
        # (`ssl.get_default_verify_paths().cafile` es None): falla TODO https con
        # `SSLCertVerificationError: unable to get local issuer certificate`, y
        # parece un problema del servidor cuando no lo es —`curl` y `requests`
        # contra el mismo host dan 200, porque `requests` usa certifi—. Hay que
        # pasárselo a mano. `context` se ignora solo si la URL es http.
        contexto = ssl.create_default_context(cafile=certifi.where())
        self._common = xmlrpc.client.ServerProxy(
            "%s/xmlrpc/2/common" % self.url, allow_none=True, context=contexto)
        self._models = xmlrpc.client.ServerProxy(
            "%s/xmlrpc/2/object" % self.url, allow_none=True, context=contexto)
        self._version = None

    @staticmethod
    def _normalizar_url(url):
        """Deja la URL como la espera `ServerProxy`.

        Escribir el host pelado (`forum.primateuy.com`) es lo natural, y
        `ServerProxy` lo rechaza con `OSError: unsupported XML-RPC protocol`,
        que no dice nada sobre lo que falta. Se asume https, que es lo que
        corresponde para cualquier destino que no sea localhost.
        """
        url = (url or "").strip().rstrip("/")
        if not url:
            raise ValueError("La configuración no tiene URL.")
        if not re.match(r"^https?://", url, re.IGNORECASE):
            url = "https://" + url
        return url

    # ------------------------------------------------------------------
    def login(self):
        """Autentica y deja el uid listo. Devuelve el uid."""
        self.uid = self._con_reintentos(
            self._common.authenticate, self.db, self.username, self.password, {})
        if not self.uid:
            raise RuntimeError(
                "No se pudo autenticar en %s (base %s) como %s: revisá usuario y "
                "clave/API key en la configuración." % (self.url, self.db, self.username))
        _logger.info("Conectado a %s | base %s | uid %s", self.url, self.db, self.uid)
        return self.uid

    @property
    def version(self):
        """Versión mayor del servidor (17, 18, 19...). Se consulta una sola vez."""
        if self._version is None:
            info = self._con_reintentos(self._common.version)
            crudo = info.get("server_version", "0")
            self._version = int(str(crudo).split(".")[0].split("-")[0] or 0)
            _logger.info("Servidor %s: versión %s", self.url, crudo)
        return self._version

    # ------------------------------------------------------------------
    def execute(self, modelo, metodo, *args, **kwargs):
        """`execute_kw` con reintentos.

        Convenio, y no es cosmético: los **posicionales** son los del método de
        Odoo (ids, valores del write...) y las **opciones** (`fields`, `order`,
        `limit`) van como kwargs. Pasar `{"fields": [...]}` como posicional lo
        deja de segundo argumento de `read` y el servidor contesta
        `Invalid field 'fields' on model ...`, que no se parece en nada a la causa.
        """
        if self.uid is None:
            self.login()
        return self._con_reintentos(
            self._models.execute_kw, self.db, self.uid, self.password,
            modelo, metodo, list(args), kwargs or {})

    def search_read(self, modelo, dominio, campos, orden=None, limite=None):
        kw = {"fields": campos}
        if orden:
            kw["order"] = orden
        if limite:
            kw["limit"] = limite
        return self.execute(modelo, "search_read", dominio, **kw)

    def read_en_lotes(self, modelo, ids, campos, tam_lote=100, etiqueta=""):
        """Lee `ids` de a `tam_lote` registros, logueando el avance X/Y.

        Los `body` de knowledge.article y los `datas` de ir.attachment pesan:
        pedir 500 de una sola vez puede hacer que el XML-RPC devuelva varios MB
        en una respuesta y que el worker se quede sin memoria.
        """
        ids = list(ids)
        total = len(ids)
        salida = []
        for inicio in range(0, total, tam_lote):
            lote = ids[inicio:inicio + tam_lote]
            salida.extend(self.execute(modelo, "read", lote, fields=campos))
            _logger.info("  %s %d/%d", etiqueta or modelo, min(inicio + tam_lote, total), total)
        return salida

    def tiene_modelo(self, modelo):
        """True si el modelo existe en el destino (para distinguir v17 de v18+).

        Se prueba el modelo DIRECTO en vez de preguntarle a `ir.model`: leer
        `ir.model` exige permisos de administración que un usuario de
        integración no tiene ni debería tener. Verificado contra un destino
        real: `Fault 4: "No puede acceder a los registros 'Models'"`, y la
        subida entera se caía en la detección, antes de escribir nada.

        Un modelo inexistente contesta `Object <modelo> doesn't exist`, que sale
        de un `ValueError` del core **sin traducir**
        (`odoo/service/model.py::execute_cr`), así que el texto es estable en
        cualquier idioma. Cualquier otro Fault se propaga: un error de permisos
        sobre un modelo que SÍ existe tiene que verse, no disfrazarse de
        «no está».
        """
        try:
            self.execute(modelo, "search_count", [])
            return True
        except xmlrpc.client.Fault as e:
            mensaje = str(getattr(e, "faultString", "") or e)
            if modelo in mensaje and ("doesn't exist" in mensaje
                                      or "does not exist" in mensaje):
                return False
            raise

    # ------------------------------------------------------------------
    def _con_reintentos(self, funcion, *args):
        ultimo = None
        for intento in range(1, self.reintentos + 1):
            try:
                return funcion(*args)
            except xmlrpc.client.Fault:
                # Error del lado del ORM: reintentar no lo va a arreglar.
                raise
            except REINTENTABLES as e:
                ultimo = e
                if intento == self.reintentos:
                    break
                espera = self.espera_base * (2 ** (intento - 1))
                _logger.warning(
                    "Fallo de transporte contra %s (%s); reintento %d de %d en %.1fs",
                    self.url, e, intento + 1, self.reintentos, espera)
                time.sleep(espera)
        raise RuntimeError(
            "No se pudo hablar con %s después de %d intentos: %s"
            % (self.url, self.reintentos, ultimo))
