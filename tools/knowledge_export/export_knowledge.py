#!/usr/bin/env python3
"""Exporta el módulo Conocimiento de Forum a PDF + HTML + manifest, y lo sube a
Documentos de Primate replicando la jerarquía.

    python3 export_knowledge.py --dry-run
    python3 export_knowledge.py --skip-upload
    python3 export_knowledge.py --root-id 87
    python3 export_knowledge.py --only-upload

Las credenciales salen de config.json (ver config.example.json). Nada hardcodeado.
"""
import argparse
import collections
import json
import logging
import os
import platform
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

# ---------------------------------------------------------------------------
# 🔴 WeasyPrint carga pango/cairo por dlopen y en macOS no mira /opt/homebrew/lib
# salvo que DYLD_FALLBACK_LIBRARY_PATH lo diga. La variable la lee dyld al
# arrancar el proceso, así que ponerla desde Python NO alcanza: hay que
# re-ejecutarse una vez. El guard evita un bucle infinito.
# ---------------------------------------------------------------------------
def _asegurar_libs_macos():
    if platform.system() != "Darwin" or os.environ.get("KEXPORT_REEXEC"):
        return
    extra = [p for p in ("/opt/homebrew/lib", "/usr/local/lib") if os.path.isdir(p)]
    if not extra:
        return
    actual = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    if all(p in actual.split(":") for p in extra):
        return
    entorno = dict(os.environ)
    entorno["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(
        [p for p in extra if p not in actual.split(":")] + ([actual] if actual else []))
    entorno["KEXPORT_REEXEC"] = "1"
    os.execve(sys.executable, [sys.executable] + sys.argv, entorno)


_asegurar_libs_macos()

from kexport import manifest as manifest_mod  # noqa: E402
from kexport import render, tree, upload      # noqa: E402
from kexport.images import ResolutorImagenes  # noqa: E402
from kexport.odoo_rpc import OdooRPC          # noqa: E402
from kexport.pdf import GeneradorPDF          # noqa: E402

_logger = logging.getLogger("kexport")


def configurar_log(directorio, verboso=False):
    directorio.mkdir(parents=True, exist_ok=True)
    archivo = directorio / "export.log"
    formato = "%(asctime)s %(levelname)-7s %(message)s"
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO,
        format=formato,
        handlers=[logging.FileHandler(archivo, mode="w", encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)])
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return archivo


PALABRAS_PRODUCCION = ("prod", "produccion", "producción")


def _huele_a_produccion(seccion):
    """¿La URL o el nombre de base de este lado parecen producción?"""
    texto = ("%s %s" % (seccion.get("url", ""), seccion.get("db", ""))).lower()
    return any(p in texto for p in PALABRAS_PRODUCCION)


def confirmar_ambientes(cfg, args, va_a_subir):
    """Muestra a qué se conecta y pide confirmación antes de escribir nada.

    Esta herramienta lee de una base y escribe en OTRA, las dos configurables
    por archivo. Equivocarse de `--config` significa subir la documentación de
    un cliente al Documentos que no es, y el error se descubre del otro lado.
    Por eso el resumen sale siempre y la confirmación es obligatoria salvo
    `--yes`.
    """
    origen, destino = cfg["origen"], cfg["destino"]
    ancho = 78
    print("\n" + "=" * ancho)
    print("  CONFIGURACIÓN: %s" % args.config)
    print("-" * ancho)
    print("  %-20s %s" % ("ORIGEN (se LEE)", origen.get("url", "?")))
    print("                      base %s · usuario %s"
          % (origen.get("db", "?"), origen.get("username", "?")))
    raiz = origen.get("root_id") if args.root_id is None else args.root_id
    print("                      alcance: %s"
          % ("subárbol del artículo %s" % raiz if raiz else "todo el workspace"))
    if va_a_subir:
        print("  %-20s %s" % ("DESTINO (se ESCRIBE)", destino.get("url", "?")))
        print("                      base %s · usuario %s"
              % (destino.get("db", "?"), destino.get("username", "?")))
        print("                      carpeta %s / %s · modo %s · conflictos: %s"
              % (destino.get("raiz", "?"), destino.get("ambiente", "?"),
                 modo_subida(cfg, args), args.on_conflict))
    else:
        print("  %-20s (no se sube: %s)"
              % ("DESTINO",
                 "--skip-upload" if args.skip_upload else "sólo exportación"))

    avisos = []
    if va_a_subir and _huele_a_produccion(destino):
        avisos.append("EL DESTINO PARECE PRODUCCIÓN: se va a ESCRIBIR en %s (base %s)"
                      % (destino.get("url"), destino.get("db")))
    if va_a_subir and args.on_conflict == "replace":
        avisos.append("Los documentos que ya existan con el mismo nombre se REEMPLAZAN")
    if avisos:
        print("-" * ancho)
        for a in avisos:
            print("  ⚠️  %s" % a)
    print("=" * ancho)

    if args.yes:
        print("  (--yes: se continúa sin preguntar)\n")
        return
    if not sys.stdin.isatty():
        raise SystemExit(
            "Sin terminal interactiva para confirmar. Pasá --yes si es una corrida "
            "desatendida y ya verificaste los ambientes de arriba.")
    respuesta = input("  ¿Continuar? (y/N) ").strip().lower()
    if respuesta not in ("y", "s", "yes", "si", "sí"):
        raise SystemExit("Cancelado.")
    print()


def ruta_en_documentos(cfg, modo, art):
    """Dónde va a quedar el archivo en Documentos, de verdad.

    En `flat` no hay subcarpetas, así que anunciar el path del árbol sería
    mentir: el manifest tiene que poder usarse para ir a buscar el archivo.
    """
    base = "%s/%s" % (cfg["destino"]["raiz"], cfg["destino"]["ambiente"])
    return base if modo == "flat" else "%s/%s" % (base, art.carpeta)


def modo_subida(cfg, args):
    """`flat` o `mirror`: la CLI pisa al config, y el default es `flat`.

    `flat` deja todos los PDFs sueltos en `<raiz>/<ambiente>` y codifica la
    posición en el árbol en el NOMBRE del archivo, para que el orden alfabético
    sea el orden jerárquico. Es lo que pidió el equipo funcional: la jerarquía
    ya está en el manifest, y las carpetas espejo les estorbaban para
    reorganizar. `mirror` es el árbol de carpetas.
    """
    modo = (args.upload_mode or cfg.get("destino", {}).get("upload_mode") or "flat").lower()
    if modo not in tree.MODOS:
        raise SystemExit("upload_mode inválido: %r. Valores: %s"
                         % (modo, ", ".join(tree.MODOS)))
    return modo


def cargar_config(ruta):
    ruta = Path(ruta)
    if not ruta.exists():
        raise SystemExit(
            "No existe %s. Copiá config.example.json a config.json y completalo." % ruta)
    with open(ruta, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
def imprimir_arbol(raices, salida=sys.stdout):
    def bajar(nodos, prefijo=""):
        ultimos = len(nodos) - 1
        for i, art in enumerate(nodos):
            rama = "└── " if i == ultimos else "├── "
            marca = ""
            if art.es_item:
                marca += " [item]"
            if not art.tiene_contenido:
                marca += " [sin contenido]"
            print("%s%s%s (id %s)%s" % (prefijo, rama, art.titulo, art.id, marca),
                  file=salida)
            bajar(art.hijos, prefijo + ("    " if i == ultimos else "│   "))

    bajar(raices)


def contar(arts):
    """Conteos del dry-run, sin bajar un solo binario."""
    import re
    total_img = total_video = total_archivo = 0
    for art in arts:
        b = art.body or ""
        total_img += len(re.findall(r"<img\b", b, re.I))
        total_video += b.count("o_knowledge_behavior_type_video")
        total_archivo += b.count("o_knowledge_behavior_type_file")
    return total_img, total_video, total_archivo


# ---------------------------------------------------------------------------
def exportar(args, cfg):
    origen = cfg["origen"]
    rpc = OdooRPC(origen["url"], origen["db"], origen["username"], origen["password"])
    rpc.login()

    root_id = args.root_id or origen.get("root_id")
    modo = modo_subida(cfg, args)
    por_id = tree.leer_articulos(
        rpc, root_id=root_id,
        incluir_privados=args.include_private,
        incluir_archivados=args.include_archived,
        limite=args.limit)
    if not por_id:
        raise SystemExit("No hay artículos en el alcance pedido.")
    raices = tree.armar_arbol(por_id, root_id=root_id, modo=modo)
    todos = tree.recorrido(raices)

    # Los `is_article_item` no generan PDF propio: en Odoo son filas de una lista
    # que el padre ya muestra dentro de su propio cuerpo. Igual van al manifest.
    exportables = [a for a in todos
                   if (args.include_items or not a.es_item) and a.tiene_contenido]

    print("\n=== Árbol en alcance ===")
    imprimir_arbol(raices)
    img, vid, arch = contar(todos)
    print("\n=== Conteos ===")
    print("  artículos en alcance : %d" % len(todos))
    print("  con contenido        : %d" % sum(1 for a in todos if a.tiene_contenido))
    print("  elementos de lista   : %d" % sum(1 for a in todos if a.es_item))
    print("  a exportar (PDF)     : %d" % len(exportables))
    print("  imágenes referenciadas: %d" % img)
    print("  bloques de video     : %d" % vid)
    print("  bloques de archivo   : %d" % arch)
    print("  profundidad máxima   : %d" % max(a.nivel for a in todos))

    if args.dry_run:
        print("\n--dry-run: no se generó ningún archivo.")
        return None

    base = Path(args.out).expanduser()
    dir_pdf = base / "pdf"
    dir_html = base / "html"
    resolutor = ResolutorImagenes(rpc, base_url=origen["url"],
                                  permitir_http=not args.no_http_images)
    generador = GeneradorPDF(motor=args.pdf_engine)
    titulos = {a.id: a.titulo for a in todos}

    filas = []
    total = len(exportables)
    _logger.info("Generando %d PDFs...", total)
    for n, art in enumerate(exportables, start=1):
        carpeta_pdf = dir_pdf / art.carpeta
        carpeta_html = dir_html / art.carpeta
        carpeta_pdf.mkdir(parents=True, exist_ok=True)
        carpeta_html.mkdir(parents=True, exist_ok=True)

        html, resumen = render.construir(
            art, resolutor, base_url=origen["url"],
            resolver_articulo=lambda i: titulos.get(i),
            quitar_titulo_repetido=not args.keep_duplicate_title)
        ruta_html = carpeta_html / art.archivo_html
        ruta_html.write_text(html, encoding="utf-8")
        ruta_pdf = carpeta_pdf / art.archivo_pdf
        motor = generador.generar(html, ruta_pdf, etiqueta="%s (id %s)" % (art.titulo, art.id))

        art._videos = resumen["videos"]
        art._irrecuperables = resumen["irrecuperables"]
        _logger.info("  [%d/%d] %s -> %s (%s, %d img, %d video)",
                     n, total, art.titulo[:50], art.carpeta + "/" + art.archivo_pdf,
                     motor, resumen["imagenes_ok"] + resumen["imagenes_inline"],
                     len(resumen["videos"]))
        if resumen["imagenes_fallidas"]:
            _logger.warning("    %d imagen(es) sin resolver en '%s'",
                            resumen["imagenes_fallidas"], art.titulo)

    # El manifest lleva TODOS los artículos del alcance, no sólo los que
    # generaron PDF: el proceso posterior necesita ver también los nodos
    # intermedios para armar la estructura del curso.
    for art in todos:
        t, s, a = tree.etiquetas_jerarquia(art)
        genero_pdf = art in exportables
        filas.append(manifest_mod.fila(
            art, t, s, a,
            pdf_rel=("pdf/%s/%s" % (art.carpeta, art.archivo_pdf)) if genero_pdf else "",
            html_rel=("html/%s/%s" % (art.carpeta, art.archivo_html)) if genero_pdf else "",
            videos=getattr(art, "_videos", []),
            ruta_documentos=ruta_en_documentos(cfg, modo, art),
            irrecuperables=getattr(art, "_irrecuperables", [])))
    ruta_manifest = base / "manifest.csv"
    manifest_mod.escribir(ruta_manifest, filas)

    print("\n=== Exportación ===")
    print("  PDFs generados : %d (%s)" % (total, generador.usos))
    print("  imágenes       : %d resueltas (%d por HTTP), %d ya inline, %d sin resolver"
          % (resolutor.resueltas, resolutor.por_http, resolutor.inline, resolutor.fallidas))
    if resolutor.irrecuperables:
        print("  ⚠ %d imagen(es) IRRECUPERABLES (file:///...): los artículos que las "
              "tienen están marcados en la columna 'Imagen irrecuperable' del manifest"
              % resolutor.irrecuperables)
    print("  manifest       : %s (%d filas)" % (ruta_manifest, len(filas)))
    if generador.fallbacks:
        print("  ⚠ %d artículo(s) cayeron al motor de respaldo" % len(generador.fallbacks))
    return base


# ---------------------------------------------------------------------------
def subir(args, cfg):
    base = Path(args.out).expanduser()
    ruta_manifest = base / "manifest.csv"
    if not ruta_manifest.exists():
        raise SystemExit("No hay %s. Corré primero la exportación." % ruta_manifest)

    destino = cfg["destino"]
    modo = modo_subida(cfg, args)
    rpc = OdooRPC(destino["url"], destino["db"], destino["username"], destino["password"])
    rpc.login()
    docs = upload.Documentos(rpc, on_conflict=args.on_conflict)
    docs.detectar()

    raiz_id = docs.ruta([destino["raiz"], destino["ambiente"]])
    _logger.info("Raíz en Documentos: %s/%s (id %s) · modo %s",
                 destino["raiz"], destino["ambiente"], raiz_id, modo)

    import csv
    with open(ruta_manifest, encoding="utf-8-sig", newline="") as fh:
        filas = list(csv.DictReader(fh, delimiter=";"))

    con_pdf = [f for f in filas if f["Archivo PDF"]]
    total = len(con_pdf)

    # En `flat` todos los archivos comparten carpeta, así que dos nombres
    # iguales serían un pisón silencioso: el segundo reemplazaría al primero y
    # el manifest seguiría diciendo que están los dos. El `<id>` del final lo
    # hace imposible, pero se verifica igual antes de escribir nada.
    if modo == "flat":
        vistos = collections.Counter(Path(f["Archivo PDF"]).name for f in con_pdf)
        chocan = sorted(n for n, c in vistos.items() if c > 1)
        if chocan:
            raise SystemExit(
                "%d nombre(s) de archivo repetidos en modo flat, se pisarían entre "
                "ellos: %s" % (len(chocan), ", ".join(chocan[:5])))
        _logger.info("Sin colisiones de nombre: %d archivos distintos", len(vistos))
    for n, fila in enumerate(con_pdf, start=1):
        ruta_pdf = base / fila["Archivo PDF"]
        if not ruta_pdf.exists():
            _logger.warning("  [%d/%d] falta el archivo %s, se saltea", n, total, ruta_pdf)
            continue
        if modo == "flat":
            # Todo suelto en la raíz: la jerarquía viaja en el NOMBRE del
            # archivo (y en el manifest), no en carpetas.
            carpeta_id, destino_log = raiz_id, "(raíz)"
        else:
            partes = Path(fila["Archivo PDF"]).parent.relative_to("pdf").parts
            carpeta_id = docs.ruta(list(partes), raiz_id)
            destino_log = "/".join(partes)
        _, accion = docs.subir(ruta_pdf, ruta_pdf.name, carpeta_id,
                               origen="forum:knowledge.article:%s" % fila["ID Odoo"])
        _logger.info("  [%d/%d] %s -> %s (%s)", n, total, ruta_pdf.name,
                     destino_log, accion)
        if args.upload_html and fila["Archivo HTML"]:
            ruta_h = base / fila["Archivo HTML"]
            if ruta_h.exists():
                docs.subir(ruta_h, ruta_h.name, carpeta_id,
                           origen="forum:knowledge.article:%s" % fila["ID Odoo"])

    docs.subir(ruta_manifest, "manifest.csv", raiz_id, origen="forum:knowledge:manifest")
    print("\n=== Subida ===")
    print("  " + docs.resumen())
    return docs


# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=str(AQUI / "config.json"),
                   help="archivo de configuración a usar. Permite tener uno por "
                        "combinación de ambientes: config.support-to-test.json, "
                        "config.prod-to-staging.json, config.prod-to-prod.json")
    p.add_argument("--yes", "-y", action="store_true",
                   help="no pedir confirmación de los ambientes (corridas desatendidas)")
    p.add_argument("--out", default=str(AQUI / "out" / "forum_knowledge"))
    p.add_argument("--root-id", type=int, help="exportar sólo este subárbol")
    p.add_argument("--dry-run", action="store_true",
                   help="sólo muestra el árbol y los conteos, no genera nada")
    p.add_argument("--skip-upload", action="store_true", help="exporta sin subir")
    p.add_argument("--only-upload", action="store_true",
                   help="sube lo ya generado, sin volver a exportar")
    p.add_argument("--limit", type=int, help="tope de artículos, para pruebas")
    p.add_argument("--include-private", action="store_true")
    p.add_argument("--include-archived", action="store_true")
    p.add_argument("--include-items", action="store_true",
                   help="generar PDF también para los is_article_item")
    p.add_argument("--upload-html", action="store_true", help="subir también los HTML")
    p.add_argument("--keep-duplicate-title", action="store_true",
                   help="no quitar el encabezado inicial que repite el título "
                        "(83 de 98 artículos lo repiten)")
    p.add_argument("--no-http-images", action="store_true",
                   help="no bajar por HTTP las imágenes que no estén en ir.attachment")
    p.add_argument("--upload-mode", choices=list(tree.MODOS),
                   help="flat (default): todos los PDFs sueltos en <raiz>/<ambiente>, "
                        "con la posición en el árbol codificada en el nombre. "
                        "mirror: árbol de carpetas espejo. Pisa a `destino.upload_mode`.")
    p.add_argument("--on-conflict", choices=["skip", "replace"], default="replace")
    p.add_argument("--pdf-engine", choices=["auto", "weasyprint", "wkhtmltopdf"],
                   default="auto")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    archivo_log = configurar_log(Path(args.out).expanduser(), args.verbose)
    cfg = cargar_config(args.config)

    # El `--dry-run` no escribe en ningún lado, así que no molesta con la
    # confirmación; cualquier otra corrida sí.
    if not args.dry_run:
        confirmar_ambientes(cfg, args, va_a_subir=not args.skip_upload)

    if not args.only_upload:
        exportar(args, cfg)
        if args.dry_run or args.skip_upload:
            print("\nLog: %s" % archivo_log)
            return
    subir(args, cfg)
    print("\nLog: %s" % archivo_log)


if __name__ == "__main__":
    main()
