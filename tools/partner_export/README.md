# Exportación de clientes para Heinwiss (carga inicial)

Heinwiss consume los clientes de Forum por la API de consultas
(`bianalytics/odoo_api_query`, `POST /api/v1/query/execute`) con la consulta guardada
**`03_clients`**. Para la carga inicial se les da un único CSV con **la misma salida**
de esa consulta, para todos los clientes, leído directo de la base con psql y en
**sólo lectura**. No se modifica ni el módulo ni la consulta guardada.

## `partners_03_clients.sql`

Una sola sesión psql, `default_transaction_read_only = on` y `statement_timeout =
5min`, con tres consultas y ninguna más:

1. que exista `api_query_definition` y que el SQL guardado de `03_clients` sea el
   esperado (el de producción al 01-10-2026, comparado con los espacios colapsados).
   Si difiere, lo muestra y corta **antes** de exportar;
2. `max(write_date)` y `max(create_date)` de `res_partner`: la fecha de corte que se le
   informa a Heinwiss;
3. la exportación: el SQL de `03_clients` con estos cambios y ningún otro:
   - sin el filtro de fecha fija (`write_date > '2026-03-01'`): todos los
     `customer_rank > 0`, sin filtrar `active` (como la consulta);
   - sin `LIMIT`/`OFFSET`;
   - `client_sync_local_date`, `client_updated_date` y `client_register_date` con el
     formato que les da la API (`datetime.isoformat()`: `2026-09-12T18:30:19.564228`,
     y `+00:00` en la que tiene zona).

   Columnas, nombres, orden y el resto de los valores, idénticos a la API, incluidos
   `client_gender` (sale «Sin definir»), `client_id_card = ref` y las cuatro columnas
   de sucursal vacías.

Lo informativo sale por stderr (`\warn`) y stdout lleva **sólo el CSV**, así que el
archivo se escribe en la máquina que corre el comando y no queda nada en el servidor.
Requiere psql 13+.

## Cómo correrlo

La base de Odoo está en el RDS; se entra por SSH al servidor de Odoo y psql toma la
clave del `odoo.conf` **dentro del servidor** (no se imprime ni viaja):

```sh
cd tools/partner_export
F=output/partners_prod_$(date +%Y%m%d_%H%M).csv
ssh -o BatchMode=yes primate_forum 'sudo -n sh -c '\''
  PGPASSWORD=$(sed -n "s/^[[:space:]]*db_password[[:space:]]*=[[:space:]]*//p" /var/odoo/forum.primateuy.com/odoo.conf) \
  LC_ALL=C.UTF-8 psql -X -q -v ON_ERROR_STOP=1 \
    -h aws-odoo.cww3o3vgjctg.us-east-2.rds.amazonaws.com -p 5432 -U odoo -d forum.primateuy.com -f -
'\''' < partners_03_clients.sql > "$F" 2> "${F%.csv}.log"
echo "exit=$?"; cat "${F%.csv}.log"
gzip -k -9 "$F"
```

🔴 El PostgreSQL **local** de ese servidor tiene bases con los mismos nombres
(`forum.primateuy.com`, `validacion-forum.primateuy.com`) que **no** son las que usa
Odoo: son copias viejas. Las reales están en el RDS (`db_host` del `odoo.conf`). La
verificación 1 lo detecta: en la copia local no existe `api_query_definition`.

`output/` está fuera del repo: el CSV tiene datos personales.

## `partner_export.py`

Alternativa anterior por XML-RPC (sin acceso a la base). Saca las mismas columnas,
pero sin los microsegundos de las fechas; ver `--help`.
