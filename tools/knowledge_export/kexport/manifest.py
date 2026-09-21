"""manifest.csv: una fila por artículo exportado.

Es el insumo del proceso posterior (Título -> Curso, Sección -> Sección,
Artículo -> Contenido), así que tiene que quedar completo y consistente aunque
el árbol tenga más de tres niveles: por eso va también el path completo real.
"""
import csv

COLUMNAS = [
    "Título", "Sección", "Artículo", "Path completo", "ID Odoo", "Parent ID",
    "Secuencia", "Archivo PDF", "Archivo HTML", "Links de video", "Ruta en Documentos",
]


def escribir(ruta, filas):
    """Vuelca las filas al CSV (UTF-8 con BOM, para que Excel no rompa las tildes)."""
    with open(ruta, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        for fila in filas:
            w.writerow(fila)
    return len(filas)


def fila(art, titulo, seccion, articulo, pdf_rel, html_rel, videos, ruta_documentos):
    return {
        "Título": titulo,
        "Sección": seccion,
        "Artículo": articulo,
        "Path completo": " > ".join(art.path),
        "ID Odoo": art.id,
        "Parent ID": art.parent_id or "",
        "Secuencia": art.sequence,
        "Archivo PDF": pdf_rel,
        "Archivo HTML": html_rel,
        "Links de video": " | ".join(videos),
        "Ruta en Documentos": ruta_documentos,
    }
