# Estado de cuenta por direccion del cliente

Prueba de concepto. Extiende `partner_statement` (OCA 17.0.1.3.0) para emitir
el estado de cuenta y los pendientes desglosados por direccion del cliente, en
lugar de una sola hoja por partner comercial.

Caso de uso: franquicias, donde cada sucursal es una direccion hija del mismo
partner comercial y necesita su propio estado de cuenta.

## Como se usa

En la lista de contactos, seleccionar el cliente (da igual si se elige la
empresa padre o una sucursal) y lanzar cualquiera de los tres estados de
cuenta. En el wizard aparece **Agrupar por**:

| Opcion | Que hace |
|---|---|
| Sin agrupar | Comportamiento nativo de OCA. El modulo queda inerte. |
| Direccion de facturacion | Una hoja por `account_move.partner_id`. |
| Direccion de entrega | Una hoja por `account_move.partner_shipping_id`. |

Conviene dejar activado **"Don't show partners with no due entries"** (que es
el default): sin el, las direcciones que no participan del modo elegido salen
como hojas vacias. Por ejemplo, agrupando por facturacion, las direcciones de
tipo entrega aparecerian vacias.

## Como funciona

En Odoo 17, `account.move.line._compute_partner_id`
(`account/models/account_move_line.py`, linea 480) siempre asigna el partner
comercial. Por eso ninguna consulta de OCA, que filtra y agrupa por
`l.partner_id`, puede separar sucursales.

Este modulo **no toca ningun dato contable**. Lo unico que cambia es la clave
de agrupamiento dentro del SQL, reemplazando `l.partner_id` por la direccion
del asiento.

### Se compone el SQL, no se copia

Cada metodo llama a `super()`, toma el SQL que haya producido la cadena de
herencia y le reescribe solo la columna de agrupamiento
(`report/statement_address_mixin.py::_forum_reescribir_sql`).

Esto no es un capricho: en FORUM ya existe `fix_partner_statement`
(LocalizacionUy), que reescribe estas mismas consultas para excluir el diario
y las cuentas de diferencia de cambio. Copiar el SQL de OCA le borraria esos
filtros en silencio. De ahi tambien la dependencia declarada: garantiza el
orden de carga. En un cliente sin LocalizacionUy se puede quitar del
`depends`.

La reescritura es estricta a proposito: si el SQL base deja de tener la forma
esperada (por ejemplo tras actualizar OCA), corta con un `UserError` en vez de
devolver numeros mal agrupados. Lo cubre `test_11`.

### Por que la suma siempre cuadra

Dos decisiones lo garantizan por construccion, no por suerte:

1. **El WHERE no se toca.** Sigue filtrando por `l.partner_id IN (...)`, y el
   wizard incluye siempre al partner comercial en el juego de partners.
2. **La expresion de agrupamiento tiene un ELSE.** Cualquier direccion que
   quede fuera del juego seleccionado cae en el partner comercial.

Resultado: ninguna linea se pierde y la suma de los estados por direccion es
identicamente igual al estado nativo del padre. Lo verifican `test_01` a
`test_03` sobre los tres reportes y los dos modos, buckets de antiguedad
incluidos.

### Metodos sobreescritos

| Modelo | Metodo |
|---|---|
| `statement.common` (via los tres reportes) | `_show_buckets_sql_q1` |
| `...activity_statement` | `_initial_balance_sql_q1`, `_display_activity_lines_sql_q1` |
| `...outstanding_statement` | `_display_outstanding_lines_sql_q1` |
| `...detailed_activity_statement` | hereda ambos mixines |

Los tres reportes se heredan **explicitamente**. Extender solo
`statement.common` no alcanza: los reportes lo heredaron por prototipo en un
modulo anterior y el registry no rehace esas clases hijas. Ademas, el
`detailed_activity_statement.py` de OCA copia
`_display_outstanding_lines_sql_q1` como atributo de clase en tiempo de
import (linea 68), asi que hay que estar antes que esa clase en el MRO.

Los mixines de Python puro llevan `__slots__ = ()`. Sin eso, Odoo falla al
rearmar el registry con `object layout differs`.

## Pagos

`account.payment.partner_id` **no se modifica**. En Odoo 17 las lineas del
pago copian ese partner tal cual (`account_payment.py`, lineas 345 y 356), asi
que cambiarlo moveria datos contables a la sucursal y dejaria al reporte OCA
nativo del padre sin ver esos pagos.

En su lugar, `account.move` lleva dos campos espejo informativos,
`forum_address_partner_id` y `forum_shipping_partner_id`, que el wizard de
registro de pago completa con la direccion de la factura que se cancela.

Reglas resultantes:

- **Factura y nota de credito**: a la direccion elegida del asiento.
- **Pago conciliado contra una factura**: sigue a la factura. En el activity
  statement se renderiza anidado bajo ella; en el outstanding, reduce su
  pendiente. Un pago atribuido a la sucursal A que cancela una factura de la
  sucursal B queda bajo B (`test_08`).
- **Pago a cuenta con direccion atribuida**: a esa direccion (`test_07`).
- **Pago a cuenta sin direccion**, incluidos todos los anteriores a este
  modulo: a la hoja del partner comercial ("nivel empresa").

Un pago que cancela facturas de sucursales distintas se deja sin atribuir a
proposito: la parte conciliada ya sigue a cada factura y el remanente no
pertenece a ninguna sucursal en particular.

## Verificacion

```sh
# Tests del modulo
.venv/bin/python _shared/community/odoo-bin -c forum-poc-statement.conf \
    -d <BASE> -u forum_partner_statement_address \
    --test-enable --test-tags /forum_partner_statement_address --stop-after-init

# Tabla comparativa nativo vs. agrupado, sobre datos reales
.venv/bin/python _shared/community/odoo-bin shell -c forum-poc-statement.conf \
    -d <BASE> --no-http --log-level=error \
    < forum/forum_partner_statement_address/tests/verificar_agrupamiento.py

# Contraste independiente, en SQL puro contra amount_residual de Odoo
psql -d <BASE> -f forum/forum_partner_statement_address/tests/sql/verificacion_direcciones.sql
```

## Limitaciones conocidas

- **XLSX con mas de un partner esta roto en OCA**, con o sin este modulo:
  `report/activity_statement_xlsx.py` linea 333 hace `objects.lang` sobre un
  recordset multiple y revienta con `Expected singleton`. Se reproduce
  seleccionando dos partners cualesquiera sin agrupar. El arreglo es
  `objects[:1].lang`, pero corresponde hacerlo en `fix_partner_statement`, que
  es el modulo propio donde ya viven los parches a OCA. PDF y HTML funcionan
  en los tres reportes y los dos modos.
- Los tests nativos de `partner_statement` no corren en una base tipo FORUM:
  dependen de los datos demo `base.res_partner_1` y `base.res_partner_2`, que
  no existen. Es previo a este modulo.
- El agrupamiento por entrega usa el `partner_shipping_id` que calculo Odoo.
  En una factura emitida al partner comercial sin direccion de entrega
  explicita, Odoo elige la primera direccion de entrega del cliente, y la
  hoja de esa direccion se lleva el movimiento.
