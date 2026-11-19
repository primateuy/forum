# Copyright 2026 Primate (https://primate.uy)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""Verificacion reutilizable del agrupamiento por direccion.

Compara, para un partner comercial, el estado de cuenta nativo de OCA contra
la suma de los estados por direccion, en los tres reportes y en los dos modos
de agrupamiento. Imprime una tabla y termina diciendo si cuadra.

Uso:

    cd clients/forum
    .venv/bin/python _shared/community/odoo-bin shell \\
        -c forum-poc-statement.conf -d <BASE> --no-http --log-level=error \\
        < forum/forum_partner_statement_address/tests/verificar_agrupamiento.py

Para apuntar a otro cliente, cambiar PARTNER / COMPANY / FECHAS de abajo.
"""

from collections import defaultdict

from odoo.fields import Date

# --- parametros ------------------------------------------------------------
PARTNER = "POC-DIR FRANQUICIAS DEMO S.A."
COMPANY = 1
D0 = Date.from_string("2026-01-01")
D1 = Date.from_string("2026-12-31")
# ---------------------------------------------------------------------------

BUCKETS = ("current", "b_1_30", "b_30_60", "b_60_90", "b_90_120", "b_over_120")
COLS = ("saldo_inicial", "cargos", "pagos", "saldo_final")
REPORTES = (
    ("ACTIVITY", "activity.statement.wizard",
     "report.partner_statement.activity_statement"),
    ("OUTSTANDING", "outstanding.statement.wizard",
     "report.partner_statement.outstanding_statement"),
    ("DETAILED ACTIVITY", "detailed.activity.statement.wizard",
     "report.partner_statement.detailed_activity_statement"),
)

emp = env["res.partner"].search([("name", "=", PARTNER)], limit=1)
assert emp, f"No se encontro el partner {PARTNER!r}"
ok_global = True


def correr(wizard, modelo, modo):
    vals = {
        "date_end": D1,
        "company_id": COMPANY,
        "forum_group_address": modo,
        # Los dos filtros esconden hojas y romperian la comparacion de totales.
        "filter_partners_non_due": False,
        "filter_negative_balances": False,
        # En el stack de FORUM el default llega en False; aca se fuerza porque
        # los buckets son justamente una de las cosas que hay que comparar.
        "show_aging_buckets": True,
    }
    if "date_start" in env[wizard]._fields:
        vals["date_start"] = D0
    w = env[wizard].with_context(active_ids=emp.ids, model="res.partner").create(vals)
    data = w._prepare_statement()
    return env[modelo]._get_report_values(list(data["partner_ids"]), data)


def filas(res):
    """Totales por hoja del reporte."""
    out = {}
    for pid, d in res["data"].items():
        agg = defaultdict(float)
        for cur in d["currencies"].values():
            agg["saldo_inicial"] += cur["balance_forward"]
            agg["saldo_final"] += cur["amount_due"]
            for ln in cur["lines"]:
                agg["cargos"] += ln.get("debit") or 0.0
                agg["pagos"] += ln.get("credit") or 0.0
            b = cur.get("buckets") or {}
            for k in BUCKETS:
                agg[k] += (b.get(k) or 0.0) if b else 0.0
        if any(abs(v) > 0.005 for v in agg.values()):
            out[env["res.partner"].browse(pid).display_name] = dict(agg)
    return out


def comparar(titulo, wizard, modelo):
    global ok_global
    print("\n" + "=" * 104)
    print(f"{titulo}  ({D0} .. {D1})")
    print("=" * 104)
    nat = filas(correr(wizard, modelo, "none"))
    claves = COLS + BUCKETS
    t_nat = {c: sum(r[c] for r in nat.values()) for c in claves}
    for modo in ("invoice", "delivery"):
        print(f"\n--- agrupado por {modo} ---")
        print(f"{'Hoja':<46}" + "".join(f"{c:>14}" for c in COLS))
        g = filas(correr(wizard, modelo, modo))
        for nombre in sorted(g):
            r = g[nombre]
            print(f"{nombre[-45:]:<46}" + "".join(f"{r[c]:>14,.2f}" for c in COLS))
        tot = {c: sum(r[c] for r in g.values()) for c in claves}
        print("-" * 104)
        print(f"{'SUMA POR DIRECCION':<46}" + "".join(f"{tot[c]:>14,.2f}" for c in COLS))
        print(f"{'ESTADO NATIVO DEL PADRE':<46}" + "".join(f"{t_nat[c]:>14,.2f}" for c in COLS))
        dif = {c: tot[c] - t_nat[c] for c in claves}
        print(f"{'DIFERENCIA':<46}" + "".join(f"{dif[c]:>14,.2f}" for c in COLS))
        print(f"{'  aging buckets':<46}" + "  ".join(
            f"{k}={tot[k]:,.2f}/{t_nat[k]:,.2f}" for k in BUCKETS))
        cuadra = all(abs(v) < 0.005 for v in dif.values())
        ok_global = ok_global and cuadra
        print("  => " + ("CUADRA" if cuadra else f"NO CUADRA: {dict(dif)}"))


for titulo, wizard, modelo in REPORTES:
    comparar(titulo, wizard, modelo)

print("\n" + "=" * 104)
print("UBICACION DE LOS PAGOS (outstanding, modo facturacion)")
print("=" * 104)
res = correr("outstanding.statement.wizard",
             "report.partner_statement.outstanding_statement", "invoice")
hay = False
for pid, d in res["data"].items():
    nombre = env["res.partner"].browse(pid).display_name
    for cur in d["currencies"].values():
        for ln in cur["lines"]:
            if str(ln["move_id"]).lower().startswith(("pago", "payment", "bnk", "csh")):
                hay = True
                print(f"  {ln['move_id']:<16} -> {nombre[-50:]:<52} abierto={ln['open_amount']:,.2f}")
if not hay:
    print("  (sin pagos a cuenta pendientes en el periodo)")

print("\n" + ("RESULTADO GLOBAL: CUADRA TODO" if ok_global else "RESULTADO GLOBAL: HAY DIFERENCIAS"))
