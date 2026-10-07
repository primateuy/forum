#!/usr/bin/env python3
"""
Convierte la salida de export.sql en el CSV para Heinwiss, con cada valor
escrito como lo devuelve la API de consultas.

La API arma cada fila con psycopg2 dentro de Odoo y la serializa con
json.dumps. Por el camino pasan tres cosas que el CSV de PostgreSQL no hace, y
que acá se repiten con el tipo de cada columna:

- Odoo registra numeric/real/double como float (odoo/sql_db.py, undecimalize):
  1990.00 sale 1990.0 y -70.00 sale -70.0.
- Las fechas pasan por isoformat(): 2026-09-24T18:59:39, con microsegundos
  sólo si no son cero y el huso (+00:00) en las que lo tienen.
- Los textos van tal cual; NULL queda vacío.

Entrada (stdin): los tipos de las columnas (nombre<TAB>tipo, de \\gdesc), la
línea @@FILAS@@ y una fila JSON (row_to_json) por línea. Salida (stdout): CSV
con encabezado.

Sólo usa la biblioteca estándar.
"""
import csv
import json
import sys
from datetime import date, datetime

MARCA = "@@FILAS@@"
FLOTANTES = ("numeric", "real", "double precision")


def tipo_base(tipo):
    # 'numeric(16,2)' -> 'numeric', 'timestamp without time zone' -> igual
    return tipo.split("(")[0].strip()


def a_texto(valor, tipo):
    """El valor como queda en el JSON de la API, sin comillas."""
    if valor is None:
        return ""
    t = tipo_base(tipo)
    if t in FLOTANTES:
        # json.dumps escribe el float con repr().
        return repr(float(valor))
    if t.startswith("timestamp"):
        return datetime.fromisoformat(valor).isoformat()
    if t == "date":
        return date.fromisoformat(valor).isoformat()
    if t == "boolean":
        return "true" if valor else "false"
    if t in ("json", "jsonb"):
        return json.dumps(json.loads(valor) if isinstance(valor, str) else valor)
    if t in ("integer", "bigint", "smallint"):
        return str(int(valor))
    return str(valor)


def main():
    columnas = []
    for linea in sys.stdin:
        linea = linea.rstrip("\n")
        if linea == MARCA:
            break
        if linea:
            nombre, tipo = linea.split("\t", 1)
            columnas.append((nombre, tipo))
    else:
        sys.exit("a_csv.py: no llegó la línea %s (¿falló export.sql?)" % MARCA)
    if not columnas:
        sys.exit("a_csv.py: no llegaron los tipos de las columnas")

    salida = csv.writer(sys.stdout, lineterminator="\n")
    salida.writerow([n for n, _ in columnas])
    filas = 0
    for linea in sys.stdin:
        if not linea.strip():
            continue
        # Los numéricos se leen como texto para no perder nada antes de
        # convertirlos como lo hace Odoo (float del texto).
        fila = json.loads(linea, parse_float=str, parse_int=str)
        if len(fila) != len(columnas):
            sys.exit("a_csv.py: la fila %d trae %d columnas y se esperaban %d"
                     % (filas + 1, len(fila), len(columnas)))
        salida.writerow([a_texto(v, t) for v, (_, t) in zip(fila.values(), columnas)])
        filas += 1
    print("filas escritas en el CSV: %d" % filas, file=sys.stderr)


if __name__ == "__main__":
    main()
