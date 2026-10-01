#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Convierte la planilla de procesamiento de Forum al CSV que lee el módulo.

La planilla (`FORUM_Procesamiento_Clientes_y_Puntos_<fecha>.xlsx`) ya viene
depurada por Forum, y de ella se usan dos hojas:

- `01_Importar_Clientes`: clientes nuevos, con sus datos y sus puntos. Van como
  `Crear cliente + puntos`.
- `02_Actualizar_puntos`: clientes que ya existen. Van como `Actualizar puntos`;
  el módulo sólo les pisa el saldo de la tarjeta, no los datos de la ficha.

El resto de las hojas (duplicados en Odoo, CI inválidas, puntos sin cliente,
repetidos) quedan fuera a propósito: es lo que Forum decidió no procesar.

El módulo lee un CSV de 14 columnas, separado por `;` y en Latin-1, y busca la
cédula EXACTA en `res_partner.vat`. Por eso la cédula de los existentes se
escribe como está guardada en la base de destino: la planilla la trae con
ceros a la izquierda hasta 8 dígitos (`00001571`) y la base no siempre.

Las cédulas de la base se pasan en un archivo, una por línea, para que el
script sirva igual contra la base local o contra producción:

    psql -d o17_support_forum -Atc "SELECT vat FROM res_partner
        WHERE l10n_latam_identification_type_id = 12 AND vat <> ''" > vats.txt

    python3 convertir_puntos.py FORUM_Procesamiento_Clientes_y_Puntos_20260930.xlsx \\
        vats.txt ../data/forum_clientes_puntos_20260930.csv
"""
import argparse
import collections
import csv
import re
import sys

import openpyxl

ENCABEZADO = [
    "Cédula", "Nombre", "Apellido", "Domicilio", "Teléfonos", "Celular",
    "Departamento", "Localidad1", "Sexo", "eMail", "FechaNac", "En Odoo",
    "Puntos", "Acción",
]
ACCION_CREAR = "Crear cliente + puntos"
ACCION_ACTUALIZAR = "Actualizar puntos"
HOJA_NUEVOS = "01_Importar_Clientes"
HOJA_ACTUALIZAR = "02_Actualizar_puntos"
DOMICILIO = "Sin dirección"

# Tildes que llegan mal codificadas desde el sistema de Forum (texto Latin-1
# leído como MacRoman): «Rodr’guez», «Su‡rez», «JosŽ». Se corrigen sólo estas;
# cualquier otro carácter fuera de Latin-1 corta la conversión para mirarlo.
MOJIBAKE = str.maketrans({"’": "í", "‡": "á", "Ž": "é"})

# La planilla trae el departamento como «Montevideo (UY)»; en Odoo es
# «Montevideo», y el módulo lo busca por nombre exacto.
SUFIJO_PAIS = re.compile(r"\s*\(UY\)\s*$", re.IGNORECASE)


def texto(valor):
    """Celda como texto limpio: sin espacios dobles y con las tildes corregidas."""
    if valor is None:
        return ""
    return " ".join(str(valor).translate(MOJIBAKE).split())


def normalizar(documento):
    """Clave de comparación: sin espacios ni ceros a la izquierda."""
    return texto(documento).lstrip("0")


def separar_nombre(valor):
    """`APELLIDO,NOMBRE` -> (nombre, apellido). Sin coma, todo va al apellido."""
    valor = texto(valor)
    if "," in valor:
        apellido, nombre = valor.split(",", 1)
        return nombre.strip(), apellido.strip()
    return "", valor


def sexo(valor):
    """El módulo sólo distingue Femenino/Masculino; lo demás queda sin dato."""
    valor = texto(valor)
    return valor if valor in ("Femenino", "Masculino") else "Desconocido"


def leer_vats(ruta):
    """normalizado -> vat tal como está en la base (el menor, si hay varios)."""
    vats = {}
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            vat = linea.strip()
            if not vat:
                continue
            clave = normalizar(vat)
            if clave not in vats or vat < vats[clave]:
                vats[clave] = vat
    return vats


def leer_hoja(libro, nombre):
    """Filas de la hoja como diccionarios por encabezado."""
    filas = libro[nombre].iter_rows(values_only=True)
    encabezado = [texto(c) for c in next(filas)]
    for fila in filas:
        if any(v is not None for v in fila):
            yield dict(zip(encabezado, fila))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("planilla", help="Excel de procesamiento de Forum")
    p.add_argument("vats", help="cédulas de la base de destino, una por línea")
    p.add_argument("salida", help="CSV a generar")
    args = p.parse_args()

    vats = leer_vats(args.vats)
    libro = openpyxl.load_workbook(args.planilla, read_only=True, data_only=True)
    conteo = collections.Counter()
    vistos = set()
    avisos = []

    with open(args.salida, "w", encoding="latin-1", errors="strict", newline="") as f:
        w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        w.writerow(ENCABEZADO)

        for r in leer_hoja(libro, HOJA_NUEVOS):
            clave = normalizar(r["Cédula"])
            if clave in vistos:
                avisos.append("repetido en la planilla, se saltea: %s" % r["Cédula"])
                continue
            vistos.add(clave)
            if clave in vats:
                # Ya existe: el módulo lo trataría como actualización igual, pero
                # que aparezca acá quiere decir que la planilla quedó vieja.
                avisos.append("nuevo que YA existe en la base: %s" % r["Cédula"])
                conteo["nuevos que ya existían"] += 1
            nombre, apellido = separar_nombre(r["Nombre"])
            w.writerow([
                vats.get(clave, clave), nombre, apellido,
                texto(r["Domicilio"]) or DOMICILIO,
                texto(r["Teléfonos"]), texto(r["Celular"]),
                SUFIJO_PAIS.sub("", texto(r["Departamento"])), texto(r["Ciudad"]),
                sexo(r["Sexo"]), texto(r["eMail"]), texto(r["FechaNac"]),
                "S" if clave in vats else "N", int(texto(r["PUNTOS"]) or 0), ACCION_CREAR,
            ])
            conteo["nuevos"] += 1

        for r in leer_hoja(libro, HOJA_ACTUALIZAR):
            clave = normalizar(r["Documento"])
            if clave in vistos:
                avisos.append("repetido en la planilla, se saltea: %s" % r["Documento"])
                continue
            vistos.add(clave)
            vat = vats.get(clave)
            if not vat:
                # Sin cliente en la base el módulo lo CREARÍA sólo con el nombre:
                # se saltea y se avisa, en vez de dar de alta una ficha vacía.
                avisos.append("a actualizar que NO existe en la base, se saltea: %s"
                              % r["Documento"])
                conteo["a actualizar que no existen (salteados)"] += 1
                continue
            nombre, apellido = separar_nombre(r["Nombre"])
            w.writerow([vat, nombre, apellido, DOMICILIO, "", "", "", "", "", "", "",
                        "S", int(r["Puntos"] or 0), ACCION_ACTUALIZAR])
            conteo["a actualizar"] += 1

    for k, v in sorted(conteo.items()):
        print("%-28s: %d" % (k, v))
    print("filas escritas              : %d" % len(vistos))
    print("salida                      : %s" % args.salida)
    for aviso in avisos[:20]:
        print("  AVISO:", aviso)
    if len(avisos) > 20:
        print("  ... y %d avisos más" % (len(avisos) - 20))


if __name__ == "__main__":
    sys.exit(main())
