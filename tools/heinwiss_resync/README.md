# Dump para que Heinwiss rellene un período sin sincronizar

Heinwiss consume la facturación y el stock de Forum por la API de consultas
(`bianalytics/odoo_api_query`, `POST /api/v1/query/execute`). En octubre de 2026
dejaron de sincronizar unos días y pidieron un dump de **`07_invoices`**,
**`06_invoice_details`** y **`15_stock_movements`** desde el 1/10 para rellenar
ese hueco.

El dump es **lo mismo que habría devuelto la API** para ese rango. El SQL no
está copiado acá: `export.sql` lo lee de `api_query_definition` en la base que se
exporta y le agrega el filtro de fechas igual que el controlador (`base_sql + "
AND campo op %s"`). Usa el mismo campo de fecha que Heinwiss usa en sus llamadas,
sacado de `api_query_log`. Todo corre en **sólo lectura**.

Verificado contra la API local (`o17_support_forum`, septiembre de 2026): son las
mismas filas y los mismos valores en los tres endpoints (32 / 45 / 69). Lo único
que cambia es cómo se escriben los valores:

| | API (JSON) | CSV |
|---|---|---|
| numéricos | `1.0`, `-70.0` | `1.00`, `-70.00` |
| timestamps (`15`) | `2026-09-24T18:59:39` | `2026-09-24 18:59:39` |

## Cómo correrlo

```sh
cd tools/heinwiss_resync
DESDE=2026-10-01 HASTA=2026-10-09 ./run.sh prod     # producción
DESDE=2026-09-01 HASTA=2026-10-01 ./run.sh local    # o17_support_forum
DESDE=... HASTA=... ./run.sh local o17_otra_base
```

`HASTA` es **exclusive**. Deja en `output/<destino>_<fecha>/`:
- un CSV por endpoint;
- un `.log` por endpoint, con la base, la definición (md5 y fecha de
  modificación), el filtro, la zona horaria y las filas;
- `consistencia.txt`;
- el `.zip` con los tres CSV, que es lo que se manda.

`prod` entra por SSH a `primate_forum` y conecta al RDS con la clave del
`odoo.conf`, leída **dentro del servidor**: no se imprime ni viaja. El CSV sale por
stdout y se escribe en la máquina que corre el comando; en el servidor no queda
nada. Es el mismo camino de `tools/partner_export`.

🔴 El PostgreSQL **local** del servidor tiene bases con los mismos nombres que
**no** son las de Odoo. `export.sql` corta si no encuentra
`api_query_definition`.

## Qué abarca el rango

Cada endpoint compara las fechas contra un campo distinto, y no todos están en la
misma zona horaria. Es lo mismo que le pasa a Heinwiss con la API:

| endpoint | campo | qué se compara |
|---|---|---|
| `06_invoice_details` | `cfe_fecha_hora_firma` | texto con huso de Uruguay (`2026-10-01T09:12:03.0000000-03:00`): los días son **días de Uruguay** |
| `07_invoices` | `invoice_local_date` | la firma convertida a la **zona de la sesión de PostgreSQL**, que es la del servidor (Odoo no la fija). El `.log` la muestra |
| `15_stock_movements` | `stock_movement_local_date` | `date_done`, guardado en **UTC** |

Si en producción la zona es UTC, `07` y `15` empiezan a las 21:00 del día anterior
en Uruguay y terminan a las 21:00 del día `HASTA - 1`. Por eso:

- **`HASTA` va un día después del último día que se quiere cubrir.** Una fecha
  futura no recorta nada.
- `07` puede traer algunas facturas de las últimas horas del 30/09 sin sus
  detalles. `consistencia.txt` las cuenta en «facturas de 07 sin detalle en 06».
  En ese número también entran los comprobantes del diario de ventas que no tienen
  líneas de producto.

Heinwiss tiene que cargar por clave (`invoice_id`, `invoice_detail_id`,
`stock_movement_id`) y no sumar: el dump se superpone con lo que ya sincronizaron.

## 🔴 `15_stock_movements` sólo devuelve salidas (en las bases locales)

La rama de las entradas filtra
`COALESCE(sl_dest.warehouse_id,0) <> COALESCE(sl_dest.warehouse_id,0)`, que es
siempre falso. En `o17_support_forum` el endpoint devuelve 626 movimientos, todos
negativos. **Reconstruir el stock con esos movimientos da sólo restas.** Antes de
mandar el dump hay que mirar la definición de producción, que sale en el `.log`
con su md5.
