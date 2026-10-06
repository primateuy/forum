# FORUM — Ventas del POS por forma de pago

Consulta detallada de los pagos del punto de venta, agrupable por forma de pago, local, sesión,
cajero y fecha, con acceso directo a la transacción del adquirente.

## Qué agrega

**Menú:** Punto de venta → Órdenes → **Ventas por forma de pago**

Abre filtrado por el día de hoy y agrupado por forma de pago, que es la consulta de cierre diario.
Tres vistas sobre los mismos datos:

- **Lista**, con el importe sumado por grupo y columnas opcionales (cajero, cliente, últimos 4
  dígitos, cuotas, comprobante, vuelto).
- **Dinámica**, con forma de pago en filas y día en columnas. Exporta a hoja de cálculo.
- **Gráfico** de barras por forma de pago.

**Filtros:** Hoy · Ayer · Esta semana · Este mes · Con transacción del adquirente · Excluir vueltos.

Los filtros de fecha cortan por día calendario en la zona horaria del usuario, no en UTC: una
venta de las 22:00 queda en el día en que se hizo y no en el siguiente.

**Agrupaciones:** forma de pago · sesión · punto de venta · cajero · cliente · **sello** · cuotas ·
fecha por día o por mes.

### Sobre el sello

El sello (Visa, Visa Débito, Mastercard) no está en el pago sino en la transacción que registra la
terminal. El módulo lo trae a `pos.payment` para poder agrupar por él.

No se usa el campo `card_type` del núcleo: en FORUM llega vacío en casi todos los pagos y, cuando
trae algo, es el código numérico del adquirente (1, 8), no la marca. Queda disponible como columna
opcional bajo el nombre *Cód. adquirente*.

El campo técnico se llama `issuer_name`, igual que en `payment.transaction`, y se muestra con la
etiqueta **Sello**.

## Configuración

### 1. Permisos

El módulo crea el grupo **Consulta de ventas por forma de pago**, en la categoría *FORUM /
Consultas* de la ficha del usuario.

> **Hay que otorgarlo junto con «Usuario» de Punto de venta.** La aplicación Punto de venta exige
> ese grupo para aparecer en la barra, así que el permiso de consulta por sí solo no alcanza para
> llegar al menú navegando.
>
> Se evaluó agregar el grupo de consulta a la aplicación para evitar esa dependencia, y se
> descartó: dejaba entrar al Tablero, que lista todos los puntos de venta con el botón de abrir
> sesión. Es más de lo que corresponde a un permiso de consulta.

### 2. Puntos de venta por usuario

Cada usuario ve **únicamente los pagos de los puntos de venta que tiene asignados** en el campo
*Puntos de venta permitidos* (`allowed_pos`, del módulo `pos_restrict`) de su ficha.

> **Un usuario sin puntos de venta asignados no ve ningún pago.** No es un error de la vista: hay
> que cargarle los PDV. El mensaje de la pantalla vacía lo indica.

La regla aplica solo al grupo de consulta. Los administradores de PDV siguen viendo todo por el
menú nativo de Pagos.

## Qué toca del sistema

| Elemento | Cómo |
|---|---|
| `pos.payment` | Agrega `config_id` (punto de venta), `user_id` (cajero) e `issuer_name` (sello), relacionados almacenados. Sin almacenar no se puede agrupar ni filtrar por ellos |
| Vista lista y búsqueda nativas | Por herencia con `xpath`. No se redefinen |
| Lista blanca de menús | El hook de instalación agrega el menú a los perfiles de sucursal de `forum_branch_security` que ya tengan lista blanca cargada |

Al instalar, Odoo calcula los dos campos nuevos para todos los pagos existentes. Es una sola vez,
pero en producción conviene hacerlo fuera del horario de caja.

## Dependencias

`point_of_sale` · `odoo_pos_oca` (aporta `payment_transaction_id`, el vínculo con la transacción
del adquirente).

De `pos_restrict` se usa el campo `allowed_pos`. No se declara como dependencia porque ya entra por
la cadena de módulos instalados en FORUM; si se instalara este módulo en una base sin él, la regla
de registro fallaría al evaluar el dominio.

## Verificado

Sobre `o17_forum` el 30/09/2026, con 49 pagos de 5 puntos de venta:

- Agrupaciones por forma de pago, punto de venta, cajero y día, con totales correctos.
- Un usuario con un solo PDV asignado ve 14 de los 49 pagos, y solo los de su local.
- El acceso directo a un pago de otro PDV devuelve error de permisos.
