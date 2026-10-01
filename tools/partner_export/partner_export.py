#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exporta TODOS los clientes de Odoo a un CSV con el formato de la API 03_clients.

Carga inicial para el sistema externo que sincroniza clientes por la API de
consultas (`bianalytics/odoo_api_query`, consulta `03_clients`). Las columnas
son exactamente las de esa consulta: mismo nombre, orden y formato, incluidos
sus valores tal como salen hoy (sexo y `client_id_card = ref`).

Lee Odoo por XML-RPC, SÓLO LECTURA (search_count / search_read). Sin SQL, sin
escrituras.

    python3 partner_export.py --env staging --dry-run
    python3 partner_export.py --env staging
"""
import argparse
import csv
import datetime
import json
import logging
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
# La conexión (reintentos, SSL con certifi) es la de knowledge_export.
sys.path.insert(0, str(AQUI.parent / "knowledge_export"))
from kexport.odoo_rpc import OdooRPC  # noqa: E402

_logger = logging.getLogger("partner_export")

TAM_LOTE = 2000
CTX = {"active_test": False}  # archivados incluidos
DOMINIO = [("customer_rank", ">", 0)]  # el mismo filtro que 03_clients, sin la fecha fija

# Campos de Odoo que hacen falta para armar las columnas de la API.
CAMPOS_BASE = [
    "id", "name", "birthdate_date", "gender", "phone_sanitized", "city", "email",
    "email_normalized", "write_date", "create_date", "is_company", "ref", "active",
]

# Columnas de 03_clients, en su orden.
COLUMNAS_API = [
    "client_id", "client_name", "client_dob", "client_gender", "client_phone",
    "client_city", "client_mail", "client_mail_is_good", "client_sync_local_date",
    "client_updated_date", "client_register_date", "client_category", "client_is_b2c",
    "client_id_card", "client_first_branch_id", "client_last_branch_id",
    "client_first_branch", "client_last_branch",
]
# Igual que la consulta: `CASE rp.gender WHEN 'F' ... WHEN 'M' ...`. Odoo guarda
# 'female'/'male', así que en la práctica sale «Sin definir»; se replica tal cual
# porque el CSV tiene que ser idéntico a lo que el sistema recibe por la API.
SEXO = {"F": "Femenino", "M": "Masculino"}


# ---------------------------------------------------------------------------
def cargar_config(env):
    ruta = AQUI / ("config.%s.json" % env)
    if not ruta.is_file():
        raise SystemExit("Falta %s (ver config.example.json y el README)." % ruta.name)
    cfg = json.loads(ruta.read_text(encoding="utf-8"))
    faltan = [k for k in ("url", "db", "username", "api_key") if not cfg.get(k)]
    if faltan:
        raise SystemExit("%s: faltan %s." % (ruta.name, ", ".join(faltan)))
    return cfg


def fecha_api(valor):
    """Datetime de Odoo como lo serializa la API (`datetime.isoformat()`).

    La API devuelve `write_date`/`create_date` crudos y los pasa por
    `isoformat()`: `2026-09-12T14:39:00`. Por XML-RPC llegan como
    `2026-09-12 14:39:00` y sin microsegundos.
    """
    return valor.replace(" ", "T") if valor else ""


def fecha_nacimiento_api(valor):
    """`TO_CHAR(birthdate_date::timestamptz, 'YYYY-MM-DD HH24:MI:SS.MS')`."""
    return "%s 00:00:00.000" % valor if valor else ""


def fila_api(p, sincronizado):
    return {
        "client_id": p["id"],
        "client_name": p["name"] or "",
        "client_dob": fecha_nacimiento_api(p["birthdate_date"]),
        "client_gender": SEXO.get(p["gender"], "Sin definir"),
        "client_phone": p["phone_sanitized"] or "",
        "client_city": p["city"] or "",
        "client_mail": p["email"] or "",
        "client_mail_is_good": "VALID" if p["email_normalized"] else "EMPTY",
        "client_sync_local_date": sincronizado,
        "client_updated_date": fecha_api(p["write_date"]),
        "client_register_date": fecha_api(p["create_date"]),
        "client_category": "Empresa" if p["is_company"] else "Persona",
        "client_is_b2c": "0" if p["is_company"] else "1",
        "client_id_card": p["ref"] or "",
        "client_first_branch_id": "",
        "client_last_branch_id": "",
        "client_first_branch": "",
        "client_last_branch": "",
    }


def columnas_adicionales(p, extras):
    """Campos pedidos con --fields: los Many2one van en `<campo>` (id) y `<campo>_name`."""
    salida = {}
    for campo in extras:
        valor = p.get(campo)
        if isinstance(valor, list) and len(valor) == 2 and isinstance(valor[1], str):
            salida[campo], salida[campo + "_name"] = valor
        elif isinstance(valor, list):
            salida[campo] = "|".join(str(v) for v in valor)
        else:
            salida[campo] = "" if valor is False or valor is None else valor
    return salida


# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--env", required=True, choices=["staging", "prod"])
    p.add_argument("--dry-run", action="store_true",
                   help="sólo cuenta y muestra la primera página; no escribe archivos")
    p.add_argument("--limit", type=int, help="tope de clientes a exportar (pruebas)")
    p.add_argument("--sleep", type=float, help="pausa entre lotes en segundos (default 0.5)")
    p.add_argument("--fields", help="campos de Odoo ADICIONALES, separados por coma; van "
                                    "al final (los Many2one como <campo> y <campo>_name)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    cfg = cargar_config(args.env)
    pausa = args.sleep if args.sleep is not None else float(cfg.get("sleep", 0.5))
    extras = [c.strip() for c in (args.fields or "").split(",") if c.strip()]
    extras = [c for c in extras if c not in CAMPOS_BASE]

    rpc = OdooRPC(cfg["url"], cfg["db"], cfg["username"], cfg["api_key"])
    rpc.login()
    print("Ambiente %s: %s (base %s) — sólo lectura" % (args.env, rpc.url, cfg["db"]))

    total = rpc.execute("res.partner", "search_count", DOMINIO, context=CTX)
    activos = rpc.execute("res.partner", "search_count", DOMINIO + [("active", "=", True)],
                          context=CTX)
    print("clientes (customer_rank > 0, con archivados): %d | activos %d | archivados %d"
          % (total, activos, total - activos))
    if args.limit:
        total = min(total, args.limit)

    campos = CAMPOS_BASE + extras
    sincronizado = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if args.dry_run:
        pagina = rpc.execute("res.partner", "search_read", DOMINIO, fields=campos,
                             order="id", limit=TAM_LOTE, context=CTX)
        print("primera página: %d registros. Primeras 5 filas como saldrían:" % len(pagina))
        for r in pagina[:5]:
            fila = fila_api(r, sincronizado)
            fila.update(columnas_adicionales(r, extras))
            print("  ", fila)
        print("lotes para la corrida completa: %d de %d (pausa %.1f s)"
              % (-(-total // TAM_LOTE), TAM_LOTE, pausa))
        print("--dry-run: no se escribió ningún archivo.")
        return

    salida_dir = AQUI / "output"
    salida_dir.mkdir(exist_ok=True)
    ruta = salida_dir / ("partners_%s_%s.csv" % (
        args.env, datetime.datetime.now().strftime("%Y%m%d_%H%M")))
    columnas = COLUMNAS_API
    exportados = activos_exp = 0
    ultimo = 0
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = None
        while exportados < total:
            lote = rpc.execute("res.partner", "search_read", DOMINIO + [("id", ">", ultimo)],
                               fields=campos, order="id",
                               limit=min(TAM_LOTE, total - exportados), context=CTX)
            if not lote:
                break
            for r in lote:
                fila = fila_api(r, sincronizado)
                adicionales = columnas_adicionales(r, extras)
                if w is None:
                    w = csv.DictWriter(f, fieldnames=columnas + list(adicionales))
                    w.writeheader()
                fila.update(adicionales)
                w.writerow(fila)
                activos_exp += 1 if r["active"] else 0
            exportados += len(lote)
            ultimo = lote[-1]["id"]
            _logger.info("  exportados %d/%d (último id %d)", exportados, total, ultimo)
            if exportados < total:
                time.sleep(pausa)

    print("\nexportados: %d | activos %d | archivados %d"
          % (exportados, activos_exp, exportados - activos_exp))
    print("archivo: %s" % ruta)


if __name__ == "__main__":
    sys.exit(main())
