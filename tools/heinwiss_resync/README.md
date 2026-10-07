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

Cada valor se escribe **como lo devuelve la API**, para que Heinwiss lo cargue
con lo que ya tiene. `export.sql` manda el tipo de cada columna y las filas en
JSON, y `a_csv.py` hace las mismas conversiones que la API:
- Odoo convierte `numeric` a `float`: `1990.00` sale `1990.0`;
- las fechas pasan por `isoformat()`: `2026-09-24T18:59:39`;
- los textos van tal cual, por ejemplo `"Efectivo - Suc GAUCHO"` con sus comillas;
- `NULL` queda vacío.

Verificado contra la API local (`o17_support_forum`, del 1/5 al 30/9 de 2026), valor
por valor y sin normalizar nada:
- en `07_invoices` (529 filas) y `15_stock_movements` (1.272) son **idénticos**;
- en `06_invoice_details` (1.139), todo lo que devuelve la API está en el CSV, pero
  la API no devuelve todo (ver abajo).

## 🔴 La API pierde filas al paginar

Las consultas guardadas no tienen un `ORDER BY` estable, y el controlador les pega
`LIMIT/OFFSET`. PostgreSQL no garantiza el mismo orden entre una página y la
siguiente. En `06_invoice_details`, del 1/5 al 30/9 en local, recorrer todas las
páginas da 1.139 filas pero **sólo 945 distintas**: unas 180 salen repetidas y
otras tantas no salen nunca. Pasa igual con 100 o con 150 filas por página. Es la
misma causa de los «duplicados» de `07` del 05-10, y además puede dejarle huecos a
Heinwiss.

El CSV no pagina, así que trae todas las filas. Arreglarlo en la API es agregar un
`ORDER BY` por la clave antes del `LIMIT/OFFSET`, pero queda fuera de este dump.

Aparte de eso, `06` puede repetir un `invoice_detail_id`: la consulta une la línea
de la factura con las líneas del pedido del PDV por producto, y si el pedido tiene
dos líneas del mismo producto, la línea de factura sale dos veces. Es así en la
consulta, y la API lo devuelve igual (14 casos en local).

## Cómo correrlo

```sh
cd tools/heinwiss_resync
DESDE=2026-10-01 HASTA=2026-10-09 ./run.sh prod     # producción
DESDE=2026-09-01 HASTA=2026-10-01 ./run.sh local    # o17_support_forum
DESDE=... HASTA=... ./run.sh local o17_otra_base
```

`HASTA` es **exclusive**. Deja en `output/<destino>_<fecha>/`:
- un CSV por endpoint, con los valores como los devuelve la API;
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
