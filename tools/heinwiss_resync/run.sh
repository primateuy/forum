#!/bin/sh
# Dump de 07_invoices, 06_invoice_details y 15_stock_movements para Heinwiss.
# SÓLO LECTURA. Uso y detalle en README.md.
#
#   ./run.sh local [base]   base local (por defecto o17_support_forum)
#   ./run.sh prod           producción: SSH a primate_forum + RDS, clave del
#                           odoo.conf leída DENTRO del servidor
#
# Rango: DESDE (inclusive) y HASTA (exclusive), por entorno.
#   DESDE=2026-10-01 HASTA=2026-10-09 ./run.sh prod
set -eu

DESTINO=${1:-}
DESDE=${DESDE:-2026-10-01}
HASTA=${HASTA:?Falta HASTA (exclusive), p. ej. HASTA=2026-10-09}
DIR=$(cd "$(dirname "$0")" && pwd)
STAMP=$(date +%Y%m%d_%H%M)
OUT="$DIR/output/${DESTINO}_$STAMP"
mkdir -p "$OUT"

correr() {
    # $1 = query_key; stdin = export.sql; stdout = CSV; stderr = log
    case "$DESTINO" in
    local)
        env -u PGTZ psql -X -q -h localhost -U odoo -d "${BASE:-o17_support_forum}" \
            -v qkey="$1" -v desde="$DESDE 00:00:00" -v hasta="$HASTA 00:00:00" -f -
        ;;
    prod)
        ssh -o BatchMode=yes primate_forum "sudo -n sh -c '
          C=/var/odoo/forum.primateuy.com/odoo.conf
          g(){ sed -n \"s/^[[:space:]]*\$1[[:space:]]*=[[:space:]]*//p\" \"\$C\" | head -1; }
          PGPASSWORD=\$(g db_password) LC_ALL=C.UTF-8 psql -X -q -v ON_ERROR_STOP=1 \
            -h \$(g db_host) -p 5432 -U \$(g db_user) -d \$(g db_name) \
            -v qkey=$1 -v desde=\"$DESDE 00:00:00\" -v hasta=\"$HASTA 00:00:00\" -f -
        '"
        ;;
    *)
        echo "uso: $0 local|prod" >&2
        exit 2
        ;;
    esac
}

[ "$DESTINO" = local ] && BASE=${2:-o17_support_forum}

for Q in 07_invoices 06_invoice_details 15_stock_movements; do
    echo "== $Q" >&2
    if ! correr "$Q" < "$DIR/export.sql" > "$OUT/$Q.csv" 2> "$OUT/$Q.log"; then
        cat "$OUT/$Q.log" >&2
        echo "ERROR en $Q: no se sigue." >&2
        exit 1
    fi
    grep -v '^---' "$OUT/$Q.log" >&2
done

# Consistencia entre cabeceras y detalles (informativo, no corta).
# 07 trae también comprobantes sin líneas de producto (pagos, asientos del
# diario de ventas), así que lo que importa es el otro sentido: detalles cuya
# cabecera no está en el archivo.
cut -d, -f1 "$OUT/07_invoices.csv" | tail -n +2 | sort -u > "$OUT/.ids_07"
cut -d, -f2 "$OUT/06_invoice_details.csv" | tail -n +2 | sort -u > "$OUT/.ids_06"
HUERFANOS=$(comm -13 "$OUT/.ids_07" "$OUT/.ids_06" | wc -l | tr -d ' ')
SIN_DETALLE=$(comm -23 "$OUT/.ids_07" "$OUT/.ids_06" | wc -l | tr -d ' ')
rm -f "$OUT/.ids_07" "$OUT/.ids_06"
{
    echo "== consistencia"
    echo "facturas en 07: $(($(wc -l < "$OUT/07_invoices.csv") - 1))"
    echo "detalles en 06: $(($(wc -l < "$OUT/06_invoice_details.csv") - 1))"
    echo "detalles cuya factura no está en 07: $HUERFANOS"
    echo "facturas de 07 sin detalle en 06: $SIN_DETALLE"
} | tee "$OUT/consistencia.txt" >&2

(cd "$OUT" && zip -q -9 "heinwiss_${DESDE}_a_${HASTA}.zip" ./*.csv)
echo "listo: $OUT/heinwiss_${DESDE}_a_${HASTA}.zip" >&2
