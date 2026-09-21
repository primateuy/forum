"""HTML -> PDF con WeasyPrint y respaldo en wkhtmltopdf.

🔴 En macOS WeasyPrint carga pango/cairo por dlopen y NO mira `/opt/homebrew/lib`
salvo que `DYLD_FALLBACK_LIBRARY_PATH` lo incluya. De eso se encarga el CLI
(`export_knowledge.py`) re-ejecutándose una vez con la variable puesta; acá sólo
se reporta con un mensaje que diga qué hacer.
"""
import logging
import shutil
import subprocess
import tempfile

_logger = logging.getLogger(__name__)

AYUDA_WEASY = (
    "WeasyPrint no pudo cargar sus librerías nativas. En macOS: "
    "`brew install pango` y correr con DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "
    "(el CLI lo hace solo). Mientras tanto se usa wkhtmltopdf."
)


class GeneradorPDF:
    """Convierte HTML a PDF, recordando qué motor funcionó."""

    def __init__(self, motor="auto"):
        self.motor_pedido = motor
        self.weasy = None
        self.wkhtml = shutil.which("wkhtmltopdf")
        self.usos = {"weasyprint": 0, "wkhtmltopdf": 0}
        self.fallbacks = []
        if motor in ("auto", "weasyprint"):
            try:
                from weasyprint import HTML  # noqa: PLC0415
                self.weasy = HTML
            except Exception as e:  # noqa: BLE001
                _logger.warning("%s (%s)", AYUDA_WEASY, e)
        if not self.weasy and not self.wkhtml:
            raise RuntimeError(
                "No hay motor de PDF disponible: WeasyPrint no carga y wkhtmltopdf "
                "no está en el PATH.")
        _logger.info("Motor de PDF: %s%s",
                     "WeasyPrint" if self.weasy else "wkhtmltopdf",
                     " (respaldo wkhtmltopdf disponible)" if self.weasy and self.wkhtml else "")

    # ------------------------------------------------------------------
    def generar(self, html, destino, etiqueta=""):
        """Escribe el PDF. Devuelve el motor usado."""
        if self.weasy and self.motor_pedido != "wkhtmltopdf":
            try:
                self.weasy(string=html).write_pdf(str(destino))
                self.usos["weasyprint"] += 1
                return "weasyprint"
            except Exception as e:  # noqa: BLE001
                # Un HTML que rompe el motor no puede tumbar la corrida entera:
                # se anota y se intenta con el otro.
                _logger.warning("WeasyPrint falló en %s (%s); se prueba wkhtmltopdf",
                                etiqueta or destino, e)
                self.fallbacks.append((str(etiqueta or destino), str(e)[:200]))
        if not self.wkhtml:
            raise RuntimeError("WeasyPrint falló y no hay wkhtmltopdf para el respaldo")
        self._wkhtmltopdf(html, destino)
        self.usos["wkhtmltopdf"] += 1
        return "wkhtmltopdf"

    def _wkhtmltopdf(self, html, destino):
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(html)
            tmp = fh.name
        cmd = [self.wkhtml, "--quiet", "--enable-local-file-access",
               "--encoding", "utf-8", "--margin-top", "18mm", "--margin-bottom", "18mm",
               "--margin-left", "15mm", "--margin-right", "15mm",
               "--footer-center", "[page] / [topage]", "--footer-font-size", "8",
               tmp, str(destino)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if res.returncode != 0 and not destino.exists():
            raise RuntimeError("wkhtmltopdf falló: %s" % (res.stderr or "").strip()[:300])
