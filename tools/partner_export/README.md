# Exportación de clientes (carga inicial de la API 03_clients)

Un CSV con **todos** los clientes de Odoo, con las mismas columnas que la consulta
`03_clients` de la API de consultas (`bianalytics/odoo_api_query`), para la carga
inicial del sistema externo que después sincroniza por esa API.

Lee Odoo **sólo en lectura** (XML-RPC, `search_count` y `search_read`): sin SQL, sin
módulos, sin escrituras.

## Configuración

Un archivo por ambiente, junto a este README: `config.staging.json` y
`config.prod.json` (fuera del repo). Copiá `config.example.json`:

| campo | qué es |
|---|---|
| `url` | URL del Odoo (`https://support-forum.primateuy.com`) |
| `db` | nombre de la base |
| `username` | usuario; alcanza con lectura de contactos |
| `api_key` | API key del usuario (Preferencias › Seguridad de la cuenta) |
| `sleep` | pausa entre lotes de 2000, en segundos (default 0.5; lo pisa `--sleep`) |

## Uso

```bash
python3 partner_export.py --env staging --dry-run       # cuenta y muestra la 1ª página
python3 partner_export.py --env staging --limit 5000    # prueba acotada
python3 partner_export.py --env staging                 # todos
python3 partner_export.py --env staging --fields country_id,street   # columnas extra
```

## Qué exporta

`res.partner` con `customer_rank > 0`, **incluidos los archivados**, ordenados por id.
Es el filtro de `03_clients` sin la fecha fija (`write_date > '2026-03-01'`).

Salida: `output/partners_<env>_<fecha>.csv` (fuera del repo: tiene datos personales),
UTF-8, coma. **Idéntico a lo que devuelve hoy `03_clients`**: las mismas 18 columnas,
en el mismo orden y con los mismos valores:

`client_id, client_name, client_dob, client_gender, client_phone, client_city,
client_mail, client_mail_is_good, client_sync_local_date, client_updated_date,
client_register_date, client_category, client_is_b2c, client_id_card,
client_first_branch_id, client_last_branch_id, client_first_branch,
client_last_branch`

Se replica la consulta tal cual, incluso donde parece raro: `client_gender` compara
contra `'F'`/`'M'` (Odoo guarda `female`/`male`, así que sale «Sin definir»),
`client_id_card` es `ref` y las cuatro columnas de sucursal van vacías. La consulta no
filtra por `active`, así que los archivados salen igual (y no hay columna que los
distinga, como en la API).

Únicas diferencias, inevitables por XML-RPC:

- `client_updated_date` y `client_register_date` llegan sin microsegundos
  (`2026-09-12T14:39:00` en vez de `2026-09-12T14:39:00.123456`).
- `client_sync_local_date` es la fecha y hora de la corrida, en UTC (`+00:00`).

Con `--fields`, los campos pedidos van al final (un Many2one en `<campo>` y
`<campo>_name`); sin `--fields` el CSV es sólo el de la API.
