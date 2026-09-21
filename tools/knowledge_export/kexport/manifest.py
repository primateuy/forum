"""manifest.csv: una fila por artículo exportado.

Es el insumo del proceso posterior (Título -> Curso, Sección -> Sección,
Artículo -> Contenido), así que tiene que quedar completo y consistente aunque
el árbol tenga más de tres niveles: por eso va también el path completo real.
"""
import csv

COLUMNAS = [
    "Título", "Sección", "Artículo", "Path completo", "ID Odoo", "Parent ID",
    "Secuencia", "Archivo PDF", "Archivo HTML", "Links de video", "Ruta en Documentos",
    "Imagen irrecuperable",
]


def escribir(ruta, filas):
    """Vuelca las filas al CSV (UTF-8 con BOM, para que Excel no rompa las tildes)."""
    with open(ruta, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        for fila in filas:
            w.writerow(fila)
    return len(filas)


def fila(art, titulo, seccion, articulo, pdf_rel, html_rel, videos, ruta_documentos,
         irrecuperables=()):
    """Una fila del manifest.

    `irrecuperables` son las imágenes `file:///C:/...` pegadas desde el disco de
    quien escribió el artículo: no existen en ninguna base y ninguna corrida
    contra producción las va a traer. La columna las marca para que en la fase
    siguiente se sepa qué artículos pedir de vuelta o revisar a mano.
    """
    irrecuperables = list(irrecuperables)
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
        "Imagen irrecuperable": ("%d: %s" % (len(irrecuperables), " | ".join(irrecuperables))
                                 if irrecuperables else ""),
    }
