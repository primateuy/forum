# Paridad del motor SQL del ajuste de inventario

Compara, campo a campo, lo que deja el **motor SQL** de `forum_partner_import`
contra lo que deja el **ORM de Odoo** aplicando las mismas celdas.

```bash
python3 paridad.py -c ../../../forum.conf -d o17_inv_med --modo ambos
python3 paridad.py -c ../../../forum.conf -d o17_inv_med --modo borrador --limite 20
```

| flag | qué hace |
|---|---|
| `--modo borrador\|publicado\|ambos` | en qué estado del ciclo de vida comparar |
| `--limite N` | cuántas celdas usar (default 30) |
| `--batch N` | batch de inventario del que se toma el staging |
| `--excluir tabla.campo,...` | campos que se sacan del diff (desvíos deliberados del core) |

Código de salida 1 si hay diferencias, 0 si no: sirve en CI.

## 🔴 Por qué compara los dos estados

La versión anterior de este arnés **normalizaba el estado del asiento** —el ORM
publica dentro de `_validate_accounting_entries` y el SQL deja en borrador— así
que comparaba **borrador contra publicado**. Eso deja **sin cobertura todo lo
que llena la transición**: los nueve campos de importe de la cabecera quedaban
en `NULL` en el camino SQL, la paridad daba 0 diferencias, y el defecto lo
encontró el cliente mirando la pantalla de revisión, con todos los asientos en
`0,00 $`.

**Una prueba de paridad tiene que comparar el mismo punto del ciclo de vida.**
Si un camino va más lejos que el otro, se lo frena; no se normaliza la
diferencia. Acá se frena el `_post` de la gemela ORM para el modo borrador.

## Cómo funciona

Las dos corridas salen del **mismo estado inicial**: cada una se hace dentro de
una transacción que termina en `rollback`, así ninguna ve lo que hizo la otra.
No hacen falta dos bases.

1. Se elige un subconjunto **determinista** de celdas que el motor SQL maneja
   (si el clasificador las mandara al ORM, las dos gemelas coincidirían por
   construcción y no se probaría nada), con **entradas, salidas y contado 0**.
2. Corrida A: camino SQL. Corrida B: se fuerza el camino ORM parcheando
   `_apl_productos_orm`.
3. En modo `publicado`, el camino SQL además **publica y concilia** (fases 3 y
   4), porque del lado ORM las dos cosas vienen adentro de
   `_validate_accounting_entries`. La conciliación va acotada a las líneas de
   **esa corrida**: la fase 4 real agrupa por el motivo del batch, que en
   producción es la corrida entera, pero en la base de pruebas hay además las
   828.781 líneas de corridas anteriores con el mismo motivo.
4. Se vuelcan las seis tablas y se comparan campo a campo.

**Se ignoran sólo**: la clave primaria, los timestamps de auditoría, el `date`
del movimiento (es el reloj de la corrida, no el motor) y las claves foráneas
que apuntan a filas creadas en la misma corrida, cuyos ids los da una secuencia.
**Todo lo demás se compara, incluido el estado del asiento.**

**Lo que se normaliza en modo `publicado`**, y sólo ahí: la numeración del diario
(`name`, `sequence_number`, `move_name`), que sale de una secuencia de Postgres y
no vuelve atrás con el rollback; y de la conciliación, `matching_number` y
`full_reconcile_id`, de los que se compara la **clase** —total, parcial o
ninguna— en vez del valor. `amount_residual`, `amount_residual_currency` y
`reconciled` se comparan de frente.

🔴 **El orden del volcado no puede depender de un campo que se desvía del core.**
Ordenar `account_move` por `ref` hacía que cada camino sacara los asientos de un
mismo producto en distinto orden, y el diff acusaba importes cruzados que no
existían. El orden va por la clave de negocio del movimiento —producto, origen,
destino, cantidad—, que es idéntica en los dos caminos; en las líneas, esa clave
va antes que cuenta, debe y haber, porque dos líneas iguales del mismo producto
empatan y el empate lo rompe el orden físico.

## 🔴 Cuándo hay que correrlo, obligatorio

**Ante cualquier cambio en `LocalizacionUy`, en `general_primate` o en nuestro
motor**, en `--modo ambos`. No es una recomendación.

Es la **única cobertura** de dos cosas:

1. **Los campos que calculamos vía ORM** (`cotizacion_historica`,
   `valor_moneda_reportes`, `moneda_reportes_id`, `tipo_cambio`,
   `amount_secondary`, `amount_residual`…). No los replicamos a propósito —su
   dueño es otro módulo— así que si ese módulo cambia su fórmula, acá no hay
   nada que avise: sólo el diff contra el ORM.
2. **Los desvíos deliberados**, que están fuera del diff y dependen de su
   invariante.

```bash
python3 paridad.py -c forum.conf -d <base> --modo ambos \
    --excluir account_move.ref,account_move_line.name
```

Código de salida 0 = pasa. Si el modo publicado dice que falta la cotización de
la moneda secundaria del día, cargala: publicar la exige de la fecha exacta.

## Desvíos deliberados del core

Lo que se aparta del core a propósito se saca del diff con `--excluir` y queda
cubierto por un invariante propio en el módulo. Hoy:

| campo | por qué |
|---|---|
| `account_move.ref` | referencia enriquecida con atributos de variante y sucursal |
| `account_move_line.name` | ídem, para que cabecera y línea digan lo mismo |

La regla: un campo se excluye **sólo** si el desvío está documentado en el
README del módulo y tiene un invariante que lo verifique. Excluir sin eso es
volver a normalizar una diferencia.
