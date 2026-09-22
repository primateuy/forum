#!/usr/bin/env python3
"""Paridad del motor SQL del ajuste de inventario contra el ORM de Odoo.

🔴 Compara los DOS estados del ciclo de vida, y esa es la razón de existir de
esta versión. El arnés anterior **normalizaba el estado del asiento** —el ORM
publica dentro de `_validate_accounting_entries` y el SQL deja en borrador— así
que comparaba borrador contra publicado. Eso deja **sin cobertura todo lo que
llena la transición**: los nueve campos de importe de la cabecera quedaban en
NULL en el camino SQL, la paridad daba 0 diferencias, y el defecto lo encontró
el cliente mirando la pantalla de revisión.

Las dos corridas salen del MISMO estado inicial: cada una se hace dentro de una
transacción que termina en rollback, así ninguna ve lo que hizo la otra.

    python3 paridad.py -c forum.conf -d o17_inv_med --modo ambos
    python3 paridad.py -c forum.conf -d o17_inv_med --modo borrador --limite 20
"""
import argparse
import os
import sys
from collections import OrderedDict

# --------------------------------------------------------------------------
# Tablas comparadas y qué se ignora de cada una.
#
# Se ignoran SOLO: la clave primaria, los timestamps y las claves foráneas que
# apuntan a filas creadas en la misma corrida (los ids se los da una secuencia,
# así que difieren por construcción). Todo lo demás se compara, incluido el
# estado del asiento.
# --------------------------------------------------------------------------
TABLAS = OrderedDict([
    ("stock_move", {
        "ignorar": {"id", "create_date", "write_date", "picking_id", "group_id",
                    "date"},   # `date` es el reloj de la corrida, no del motor
        "orden": "product_id, location_id, location_dest_id, product_uom_qty",
    }),
    ("stock_move_line", {
        "ignorar": {"id", "create_date", "write_date", "move_id", "picking_id",
                    "date"},   # ídem
        "orden": "product_id, location_id, location_dest_id, quantity",
    }),
    ("stock_valuation_layer", {
        "ignorar": {"id", "create_date", "write_date", "stock_move_id",
                    "account_move_id", "stock_valuation_layer_id", "account_move_line_id"},
        "orden": "product_id, quantity, value",
    }),
    ("account_move", {
        "ignorar": {"id", "create_date", "write_date", "stock_move_id",
                    "message_main_attachment_id", "access_token"},
        "orden": "(SELECT m.product_id FROM stock_move m WHERE m.id = t.stock_move_id), ref",
    }),
    ("account_move_line", {
        "ignorar": {"id", "create_date", "write_date", "move_id", "statement_line_id"},
        "orden": "product_id, account_id, debit, credit",
    }),
    ("stock_quant", {
        "ignorar": {"id", "create_date", "write_date", "in_date"},
        "orden": "product_id, location_id",
    }),
])


def columnas(cr, tabla, ignorar):
    cr.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_name = %s ORDER BY column_name""", (tabla,))
    return [c for (c,) in cr.fetchall() if c not in ignorar]


def volcar(cr, tabla, desde_id, cfg):
    """Filas de `tabla` creadas en esta corrida, normalizadas y ordenadas."""
    cols = columnas(cr, tabla, cfg["ignorar"])
    sel = ", ".join('t."%s"' % c for c in cols)
    cr.execute("SELECT %s FROM %s t WHERE t.id > %%s ORDER BY %s"
               % (sel, tabla, cfg["orden"]), (desde_id,))
    return cols, cr.fetchall()


def max_ids(cr):
    ids = {}
    for tabla in TABLAS:
        cr.execute("SELECT coalesce(max(id), 0) FROM %s" % tabla)
        ids[tabla] = cr.fetchone()[0]
    return ids


# --------------------------------------------------------------------------
def elegir_celdas(env, batch, limite):
    """Subconjunto determinista: celdas que el motor SQL maneja, con entradas,
    salidas y contado 0. Sin ese mix la comparación no prueba las tres ramas."""
    cr = env.cr
    cr.execute("""
        SELECT q.product_id, q.location_id, q.quantity
          FROM stock_quant q
          JOIN stock_location l ON l.id = q.location_id AND l.usage = 'internal'
          JOIN product_product pp ON pp.id = q.product_id
          JOIN product_template pt ON pt.id = pp.product_tmpl_id
         WHERE q.company_id = 1 AND q.quantity > 10 AND pt.tracking = 'none'
           AND q.reserved_quantity = 0
           AND q.lot_id IS NULL AND q.package_id IS NULL AND q.owner_id IS NULL
           AND (SELECT x.value_text FROM ir_property x WHERE x.name='property_valuation'
                 AND (x.res_id='product.category,'||pt.categ_id OR x.res_id IS NULL)
                 AND (x.company_id=1 OR x.company_id IS NULL)
                ORDER BY (x.res_id IS NULL),(x.company_id IS NULL) LIMIT 1) = 'real_time'
           AND (SELECT x.value_text FROM ir_property x WHERE x.name='property_cost_method'
                 AND (x.res_id='product.category,'||pt.categ_id OR x.res_id IS NULL)
                 AND (x.company_id=1 OR x.company_id IS NULL)
                ORDER BY (x.res_id IS NULL),(x.company_id IS NULL) LIMIT 1) = 'fifo'
           AND NOT EXISTS (SELECT 1 FROM stock_valuation_layer sl
                            WHERE sl.product_id = q.product_id AND sl.company_id = 1
                              AND sl.remaining_qty < 0)
           AND (SELECT count(*) FROM stock_quant q2 WHERE q2.product_id = q.product_id
                 AND q2.location_id = q.location_id AND q2.lot_id IS NULL
                 AND q2.package_id IS NULL AND q2.owner_id IS NULL) = 1
         ORDER BY q.id LIMIT %s
    """, (limite,))
    return cr.fetchall()


def sembrar(env, batch, celdas):
    """Escribe las celdas en el staging y devuelve sus row_num."""
    cr = env.cr
    t = batch._staging_name()
    filas = []
    for i, (pid, lid, qty) in enumerate(celdas):
        # Mix deliberado: entrada, salida y contado 0.
        nueva = {0: float(qty) + 7, 1: float(qty) - 3, 2: float(qty)}[i % 3]
        cr.execute("""
            INSERT INTO {t} (product_id, location_id, company_id, cantidad, apply_seq,
                             xid, procesado, resultado_carga)
            VALUES (%s, %s, 1, %s, %s, 'paridad', true, 'ok') RETURNING row_num
        """.format(t=t), (pid, lid, nueva, 900000 + i))
        filas.append(cr.fetchone()[0])
    return filas


def correr(env, batch, celdas, via, publicar):
    """Aplica las celdas por `via` ('sql' u 'orm'). Devuelve los volcados."""
    from odoo.addons.forum_partner_import.models.forum_import_batch_inventario_apply import (
        CONTEXTO_SIN_WMS)
    cr = env.cr
    antes = max_ids(cr)
    filas = sembrar(env, batch, celdas)
    b = batch.with_context(**CONTEXTO_SIN_WMS)

    restaurar = []
    if via == "orm":
        # Se fuerza el camino ORM para TODOS los productos: si no, el
        # clasificador los manda por SQL y la comparación no probaría nada.
        tipo = type(batch)
        original = tipo._apl_productos_orm

        def todos_por_orm(self, t, fs):
            self.env.cr.execute(
                "SELECT DISTINCT product_id FROM {t} WHERE row_num = ANY(%s)".format(t=t),
                (list(fs),))
            return {r[0] for r in self.env.cr.fetchall()}

        tipo._apl_productos_orm = todos_por_orm
        restaurar.append((tipo, "_apl_productos_orm", original))

    if via == "orm" and not publicar:
        # 🔴 El ORM publica dentro de `_validate_accounting_entries`. Para
        # comparar BORRADOR contra BORRADOR hay que frenarlo justo ahí, que es
        # la transición que antes tapaba las diferencias.
        AM = type(env["account.move"])
        original_post = AM._post
        AM._post = lambda self, soft=True: self
        restaurar.append((AM, "_post", original_post))

    try:
        cuenta = b._apl_procesar_filas(filas)
    finally:
        for obj, nombre, valor in restaurar:
            setattr(obj, nombre, valor)

    if publicar and via == "sql":
        moves = env["account.move"].search([("id", ">", antes["account_move"])])
        moves._post(soft=False)

    volcados = {}
    for tabla, cfg in TABLAS.items():
        volcados[tabla] = volcar(cr, tabla, antes[tabla], cfg)
    return cuenta, volcados


def comparar(vol_sql, vol_orm, excluir_campos):
    """Diferencias por tabla. Devuelve {tabla: [(fila, columna, sql, orm)]}."""
    dif = {}
    for tabla in TABLAS:
        cols_s, filas_s = vol_sql[tabla]
        cols_o, filas_o = vol_orm[tabla]
        if cols_s != cols_o:
            dif[tabla] = [("(esquema)", "columnas distintas", str(cols_s), str(cols_o))]
            continue
        if len(filas_s) != len(filas_o):
            dif.setdefault(tabla, []).append(
                ("(cantidad)", "filas", len(filas_s), len(filas_o)))
        d = []
        for n, (fs, fo) in enumerate(zip(filas_s, filas_o)):
            for col, vs, vo in zip(cols_s, fs, fo):
                if col in excluir_campos.get(tabla, ()):
                    continue
                if vs != vo:
                    d.append((n, col, vs, vo))
        if d:
            dif.setdefault(tabla, []).extend(d)
    return dif


# --------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-c", "--config", required=True)
    p.add_argument("-d", "--db", required=True)
    p.add_argument("--odoo-path", default="/Users/darylyturraldelopez/Odoo/shared/odoo/community")
    p.add_argument("--batch", type=int, default=11)
    p.add_argument("--limite", type=int, default=30)
    p.add_argument("--modo", choices=["borrador", "publicado", "ambos"], default="ambos")
    p.add_argument("--excluir", default="",
                   help="campos a excluir del diff, formato tabla.campo,tabla.campo")
    args = p.parse_args()

    sys.path.insert(0, args.odoo_path)
    import odoo
    from odoo.tools import config
    config.parse_config(["-c", args.config, "-d", args.db])
    registry = odoo.registry(args.db)

    excluir = {}
    for par in filter(None, args.excluir.split(",")):
        tabla, campo = par.split(".", 1)
        excluir.setdefault(tabla, set()).add(campo)

    modos = ["borrador", "publicado"] if args.modo == "ambos" else [args.modo]
    codigo = 0
    for modo in modos:
        publicar = modo == "publicado"
        volcados = {}
        celdas = None
        for via in ("sql", "orm"):
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
                batch = env["forum.import.batch"].browse(args.batch)
                if celdas is None:
                    celdas = elegir_celdas(env, batch, args.limite)
                cuenta, volcados[via] = correr(env, batch, celdas, via, publicar)
                print("  %-9s vía %-3s -> aplicadas=%s asientos=%s"
                      % (modo, via, cuenta["aplicado"], cuenta["asientos"]))
                cr.rollback()   # cada camino parte del MISMO estado

        print("\n=== PARIDAD en estado %s (%d celdas) ===" % (modo.upper(), len(celdas)))
        dif = comparar(volcados["sql"], volcados["orm"], excluir)
        if not dif:
            for tabla in TABLAS:
                print("  OK    %-24s %d filas idénticas"
                      % (tabla, len(volcados["sql"][tabla][1])))
        for tabla, lista in dif.items():
            codigo = 1
            campos = sorted({c for _, c, _, _ in lista})
            print("  FALLA %-24s %d diferencias en %d campo(s)"
                  % (tabla, len(lista), len(campos)))
            visto = set()
            for fila, col, vs, vo in lista:
                if col in visto:
                    continue
                visto.add(col)
                print("          %-34s sql=%-14r orm=%r" % (col, vs, vo))
        print()
    return codigo


if __name__ == "__main__":
    sys.exit(main())
