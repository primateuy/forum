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
from datetime import date
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
        # 🔴 Los quants se ACTUALIZAN, no se crean: filtrar por `id > max` no
        # compararía ni una fila y la tabla quedaría con cobertura falsa.
        "filtro": "celdas",
    }),
])


def columnas(cr, tabla, ignorar):
    cr.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_name = %s ORDER BY column_name""", (tabla,))
    return [c for (c,) in cr.fetchall() if c not in ignorar]


def volcar(cr, tabla, desde_id, cfg, celdas):
    """Filas de `tabla` que tocó esta corrida, normalizadas y ordenadas."""
    cols = columnas(cr, tabla, cfg["ignorar"])
    sel = ", ".join('t."%s"' % c for c in cols)
    if cfg.get("filtro") == "celdas":
        pares = [(p, l) for p, l, _ in celdas]
        cr.execute("SELECT %s FROM %s t WHERE (t.product_id, t.location_id) IN %%s "
                   "ORDER BY %s" % (sel, tabla, cfg["orden"]), (tuple(pares),))
    else:
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
    """, (max(limite - 2, 1),))
    celdas = cr.fetchall()

    # 🔴 Caso de borde FIJO: producto SIN valor FIFO, cuya salida genera una capa
    # de valor exactamente 0. Ahí no aplica ninguna rama del `create` de
    # tchistorico, y ese hueco escondía una diferencia real en
    # `moneda_reporte_id` que sólo apareció al subir la muestra de 9 a 12
    # celdas. Va siempre, no por azar del `LIMIT`.
    cr.execute("""
        SELECT q.product_id, q.location_id, q.quantity
          FROM stock_quant q
          JOIN stock_location l ON l.id = q.location_id AND l.usage = 'internal'
          JOIN product_product pp ON pp.id = q.product_id
          JOIN product_template pt ON pt.id = pp.product_tmpl_id
         WHERE q.company_id = 1 AND q.quantity > 10 AND pt.tracking = 'none'
           AND q.reserved_quantity = 0
           AND q.lot_id IS NULL AND q.package_id IS NULL AND q.owner_id IS NULL
           -- La marca del borde: capas CON saldo en cantidad pero SIN valor, así
           -- la salida vale exactamente 0 y no aplica ninguna rama del create.
           AND EXISTS (SELECT 1 FROM stock_valuation_layer sl
                        WHERE sl.product_id = q.product_id AND sl.company_id = 1
                          AND sl.remaining_qty > 0 AND coalesce(sl.remaining_value, 0) = 0)
           AND NOT EXISTS (SELECT 1 FROM stock_valuation_layer sl
                            WHERE sl.product_id = q.product_id AND sl.company_id = 1
                              AND sl.remaining_qty < 0)
           AND (SELECT count(*) FROM stock_quant q2 WHERE q2.product_id = q.product_id
                 AND q2.location_id = q.location_id AND q2.lot_id IS NULL
                 AND q2.package_id IS NULL AND q2.owner_id IS NULL) = 1
         ORDER BY q.id LIMIT 2
    """)
    borde = [c for c in cr.fetchall() if c not in celdas]
    if not borde:
        print("  AVISO: no hay productos sin valor FIFO en esta base; el caso de "
              "borde de moneda_reporte_id NO se está cubriendo.")
    return celdas + borde


def sembrar(env, batch, celdas):
    """Escribe las celdas en el staging y devuelve sus row_num."""
    cr = env.cr
    t = batch._staging_name()
    filas = []
    for i, (pid, lid, qty) in enumerate(celdas):
        # Mix deliberado: entrada, salida y contado 0.
        # Mix deliberado: entrada, salida y contado 0. Las dos últimas celdas
        # son las del caso de borde y van SIEMPRE como salida, que es donde la
        # capa queda en valor 0.
        if i >= len(celdas) - 2 and len(celdas) > 2:
            nueva = float(qty) - 3
        else:
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
        # 🔴 Con `action_post` y como el usuario del proceso, que es exactamente
        # lo que hace la fase 3 del módulo. Publicar con `_post(soft=False)` a
        # mano y como el usuario de la sesión dejaba `parent_state` y
        # `move_name` sin recomputar en las líneas y cambiaba `write_uid`:
        # tres diferencias que eran del ARNÉS, no del motor. Se comprobó contra
        # la corrida real, donde esas columnas están bien en 1.657.568 renglones.
        usuario = batch.inventory_user_id or env.user
        env = env(user=usuario)          # también el flush: escribir deja write_uid
        moves = env["account.move"].search([("id", ">", antes["account_move"])])
        moves.action_post()


    # 🔴 El volcado lee la base con SQL directo, así que lo que el ORM tenga
    # pendiente de calcular todavía no está ahí. Sin este flush, `move_name` y
    # `parent_state` de las líneas aparecían sin actualizar después de publicar
    # y parecían un defecto del motor cuando eran del arnés.
    env.flush_all()
    volcados = {}
    for tabla, cfg in TABLAS.items():
        volcados[tabla] = volcar(cr, tabla, antes[tabla], cfg, celdas)
    return cuenta, volcados


def revisar_precondiciones(env, modo):
    """En modo publicado hace falta la cotización de la moneda secundaria.

    Publicar exige la tasa de la FECHA EXACTA (la copia vieja de
    `aml_secondary_currency` que corre en estas bases no acepta la del día
    anterior). Sin ella el `_post` levanta UserError y el arnés reventaba con un
    traceback que no decía qué faltaba.
    """
    if modo != "publicado":
        return None
    cia = env.company
    secundaria = getattr(cia, "secondary_currency_id", None) or getattr(
        cia, "monedaDeReporte", None)
    if not secundaria:
        return None
    hoy = date.today()
    tasa = env["res.currency.rate"].search_count([
        ("currency_id", "=", secundaria.id), ("name", "=", hoy)])
    if tasa:
        return None
    return ("Falta la cotización de %s para %s: publicar la exige de la FECHA "
            "EXACTA. Cargala y volvé a correr el modo publicado."
            % (secundaria.name, hoy))


# 🔴 La numeración del diario sale de una secuencia de Postgres, que no vuelve
# atrás con el rollback: la segunda corrida saca números distintos por
# construcción. No es una diferencia del motor. Que la numeración sea correcta
# lo cubren los invariantes 5b y 5c del módulo, no este arnés.
SECUENCIA_DIARIO = {
    "account_move": {"name", "sequence_number"},
    "account_move_line": {"move_name"},
}


def comparar(vol_sql, vol_orm, excluir_campos, publicado=False):
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
                if publicado and col in SECUENCIA_DIARIO.get(tabla, ()):
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
        with registry.cursor() as cr:
            env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
            falta = revisar_precondiciones(env, modo)
            cr.rollback()
        if falta:
            print("\n=== PARIDAD en estado %s: NO SE PUDO CORRER ===" % modo.upper())
            print("  " + falta)
            codigo = 2
            continue
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
        dif = comparar(volcados["sql"], volcados["orm"], excluir, publicar)
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
