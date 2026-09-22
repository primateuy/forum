# Reparación de los asientos en borrador del ajuste de inventario

Para asientos **ya creados** por una versión del módulo **anterior a la
17.0.1.4.0**, que quedaron esperando revisión (la fase 3 no se corrió).

```bash
psql -h <host> -U <usuario> -d <base> -v BATCH=11 \
     -f reparar_borradores_ajuste.sql
```

`BATCH` es el id del batch de inventario. El script **no hace `COMMIT` solo**:
imprime los controles de antes y después y te deja decidir.

## Qué arregla

| | |
|---|---|
| 1 | los nueve importes de la cabecera, que quedaban en `NULL` y por eso la lista mostraba **todo en `0,00 $`** |
| 2 | el resto de campos calculados-almacenados de cabecera y línea |
| 3 | la referencia, al formato legible con código, atributos y sucursal |
| 4 | el **residual de la línea**, sin el cual la conciliación no tiene con qué trabajar |

## Qué NO toca

- **Asientos publicados.** Al publicar, el ORM ya completó todo.
- **El debe y el haber de las líneas.** Siempre estuvieron bien: acá no se toca
  ni uno. Lo que estaba vacío era el totalizador de la cabecera.
- **Las conciliaciones ya existentes.** Las líneas con una conciliación parcial
  se saltean y el script informa cuántas fueron.
- Nada que no sea de este ajuste.

## 🔴 Por qué hay que completar el residual

`amount_residual` es un calculado-almacenado cuyo `@api.depends`
(`account_move_line.py:749`) **no incluye `move_id.state`**: se calcula al
**crear** la línea y publicar no lo vuelve a tocar. Las líneas que insertó una
versión anterior del motor quedaron en cero, y **`reconcile()` sobre un residual
cero no hace nada y no falla**: la conciliación correría limpia, informaría 0
errores y no conciliaría nada.

El script replica el compute para líneas **sin conciliación parcial**, que es el
caso de los borradores: residual = saldo redondeado en la moneda de la compañía,
residual en moneda = `amount_currency` redondeado en la de la línea, y
`reconciled` sólo si los dos dan cero.

## 🔴 Cómo se identifican nuestros asientos

Por **`stock_move.origin`**, donde el módulo escribe el motivo del batch
(`inventory_reason`). Es la única marca propia.

No sirve la **ventana de fechas**: en la misma ventana hay ajustes hechos a mano
por gente, y ya nos confundieron una vez al leer el invariante `3a bis`. Medido
sobre la base del peor caso: **835.309 movimientos con nuestro origen y 12.629
sin él**. Tampoco sirve `stock_move.reference`, que replica el texto de Odoo y
lo comparten los ajustes manuales; ni el **staging**, que puede estar vacío
después de la corrida.

## Idempotencia

Cada `UPDATE` lleva su condición de cambio, así que correrlo dos veces deja el
mismo resultado. Verificado: en la segunda corrida los cinco `UPDATE` devuelven
**0 filas**.

## Verificado

Sobre `o17_inv_med`, fabricando el defecto —300 asientos vueltos a borrador con
la cabecera vacía y la referencia vieja, que es como están en support— y
corriendo la reparación dentro de una transacción con `ROLLBACK`:

| control | resultado |
|---|---|
| cabecera sin importe | 0 |
| referencia vieja | 0 |
| referencia de más de 120 caracteres | 0 |
| cabecera distinta de la suma de sus líneas | 0 |
| referencia distinta entre cabecera y línea | 0 |
| publicados tocados | 0 |
| líneas conciliables sin residual | 0 |
| líneas salteadas por conciliación existente | 0 |
| segunda corrida | todos los `UPDATE` en 0 filas |

Ejemplo del resultado:

```
[2165182104513009] Camisa M/L Pail Cttn Print (4XL, VARIANTE 4, FANTASIA 13) · COLON (Neratur SA) · Cantidad d
```

## Después de correrlo

Volvé a correr los invariantes del batch. El **4g** («referencia enriquecida mal
formada») tiene que pasar de decenas de miles de violaciones a **0**.

Y si los asientos se van a publicar, tené presente que después de publicarlos hay
que correr la **fase 4 (conciliación)**: es lo que hace el ORM al validar las
capas y lo que verifica el invariante **9**. El residual que completa este script
es justamente lo que esa fase necesita.
