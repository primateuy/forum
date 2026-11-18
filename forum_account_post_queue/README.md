# FORUM - Cola de registro de facturas

## El problema

Seleccionar muchas facturas en la lista y usar **Acciones → Registrar asientos**
termina en `RecursionError`. Es un bug del core de Odoo 17: el campo
`discount_allocation_dirty` no está almacenado y su `compute` dispara una
escritura que vuelve a leerlo, así que la recursión crece con la cantidad de
líneas de la tanda y se pasa del límite de Python.

Medido en la base de FORUM, con facturas en el tope de 199 líneas del punto de
emisión:

| Facturas en la tanda | Apuntes | Resultado |
|---|---|---|
| 1 | 203 | registra |
| 2 | 405 | registra |
| 3 | 608 | `RecursionError` |

Y aun sin el error, registrar 119 facturas tarda unas dos horas: ~66 segundos
por factura. No es algo que se pueda esperar con el navegador abierto.

### El bug no es del posteo, es de cualquier escritura

Lo que recursiona es `_sync_dynamic_lines`, que corre en **cada `write` sobre una
factura en borrador** para reconstruir sus líneas de impuestos, descuentos y
plazos de pago. Registrar en lote es solo una de las formas de dispararlo:
marcar un campo propio en 119 borradores con un único `write` rompe igual.

Por eso todos los campos de la cola se escriben con `_forum_write_cola()`, que
pasa `skip_invoice_sync=True` — la misma llave que usa el core en
`_sync_dynamic_lines`. Los campos de la cola no participan de ninguna línea
dinámica, así que saltear el recálculo es exacto, no un atajo. Sin eso, encolar
sería tan caro y tan frágil como registrar.

## Qué hace este módulo

No registra en el momento: deja las facturas **en cola** y un cron las va
registrando de a tandas, commiteando cada tanda.

1. El usuario selecciona las facturas y usa **Registrar asientos**, como siempre.
2. En vez del error aparece un aviso: *"N facturas quedaron en cola"*.
3. Las facturas quedan en borrador marcadas **En cola**.
4. Cada 10 minutos el cron registra una tanda y commitea. Lo que salió, salió.
5. Si una factura falla, queda marcada **Error al registrar** con el motivo en
   el chatter, y la cola sigue con las demás.

**Confirmar una factura sola desde su formulario no cambia en nada** y la saca
de la cola automáticamente. Quien necesita ver una registrarse en el momento,
entra y la confirma.

## Parámetros

| Clave (`ir.config_parameter`) | Default | Qué controla |
|---|---|---|
| `forum.post_queue_max_lines` | 199 | Líneas de factura por tanda. Es el mismo número que el "Cantidad máxima de líneas" del punto de emisión: una factura de venta grande entra sola, varias chicas entran juntas. |
| `forum.post_queue_min_moves` | 2 | A partir de cuántas facturas seleccionadas se encola. Con 2, seleccionar una sola sigue registrando al instante. |
| `forum.post_queue_max_lines_per_run` | 3000 | Tope por corrida del cron, para no pasarse del `limit_time_real`. Si queda cola, el cron se auto-dispara. |

## Decisiones de diseño

**No se toca `_post` del core.** El módulo no cambia cómo se registra una
factura, solo *cuándo*. Registrar de a una se comporta exactamente igual que sin
el módulo instalado.

**Se commitea cada tanda.** Es lo que permite que una tanda que falle no voltee
las que ya se registraron. También es lo que hace que corra el hook de postcommit
que emite el CFE: sin commit, el CFE no se emitiría nunca.

**Las tandas van en orden de fecha.** La numeración y la secuencia de CFE se
asignan al registrar, así que registrar desordenado dejaría los números
desordenados respecto de las fechas.

**Cada tanda se registra con la compañía y el usuario que la encolaron**, no como
superusuario, para que las reglas de acceso y el chatter queden igual que si lo
hubiera hecho la persona a mano.

**Las facturas de fecha futura salen de la cola.** Sin forzar, Odoo no las
registra: las deja con `auto_post` para que las tome el cron del core el día que
corresponde. Si las dejáramos marcadas, esta cola las volvería a tomar cada 10
minutos para siempre.

## Alcance

Cubre la acción **Registrar asientos** de la lista de facturas, que es la única
vía de registro masivo de Odoo 17 (la lista no tiene botón propio; el formulario
registra de a una).

Otros flujos que registran en lote desde código — por ejemplo confirmar muchos
pedidos y facturarlos de una — siguen como están y podrían chocar con el mismo
bug del core. Se pueden enganchar a esta misma cola si hace falta.

## Pendiente conocido

El asistente de `pos_sale_order_sync_autoinvoice` genera las facturas en
borrador y no las registra. Se le podría agregar un check *"Registrar las
facturas generadas"* que las encole en el mismo paso, para cerrar el circuito.
Queda fuera de esta versión por decisión de alcance.
