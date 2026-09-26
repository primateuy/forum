# Perfil Usuario Sucursal (`forum_branch_security`)

El perfil de permisos del usuario de local. Se apoya en el ancla de sucursal de
`retail_branch`, que vive en `retail-ecommerce/` y no depende de ningún módulo de pago.

## Para el administrador funcional

> ⚠️ **Dar de alta a alguien en el perfil son dos pasos.** Asignarle *Usuario Sucursal* no
> le quita *Ver costo de productos*: hay que destildarlo aparte o va a seguir viendo el
> costo mientras el resto del recorte funciona. Ver
> [Asignar el perfil son DOS pasos](#asignar-el-perfil-son-dos-pasos-no-uno).

### Qué podés tocar y qué se revierte

Esta es la regla, y está partida a propósito. Lo que cambia seguido y es de bajo riesgo
queda bajo control de la interfaz; lo que rompe cosas si queda mal se restaura con un
`-u`.

#### Podés cambiarlo desde la interfaz y **sobrevive** a un update

| Qué | Dónde |
|---|---|
| La lista blanca de menús | Grupos → Usuario Sucursal → pestaña **Menús** |
| Campos ocultos o de solo lectura | pestaña **Campos** |
| Reportes bloqueados | pestaña **Reportes** |

#### Se **revierte** en el próximo update

| Qué | Por qué |
|---|---|
| Los dominios de restricción de registro | pestaña **Registros**. Mal puestos dejan ver datos de otras sucursales |
| Las ACL del perfil | pestaña **Permisos**. Ya rompieron el `load_pos_data` del POS en dos bases |
| `implied_ids` y `allowed_use_debug_mode` del grupo | Definen qué es el perfil |

Si necesitás un cambio permanente en algo de la segunda tabla, pedilo como cambio de
código. Tocarlo a mano funciona hasta el próximo deploy y después se pierde en silencio.

## La vista consolidada

**Ajustes → Usuarios y Compañías → Grupos → Usuario Sucursal** muestra en una pantalla las
cinco capas: menús, registros, campos, reportes y permisos. Antes había que mirar en cinco
lugares distintos.

## Cómo está hecho, y por qué

### No se crea ni se archiva una sola `ir.rule`

Las reglas multicompañía de core son **globales**, y las globales se combinan con **AND**.
Agregar una regla nunca amplía lo que otra permite ver, y archivarlas para ensanchar deja
la base sin su recorte de compañía.

Todo el recorte va por `generic.security.model.restriction`, que AND-ea un dominio extra
dentro de `ir.rule._compute_domain`. Todo el ensanche va por `company_ids` —que sincroniza
`retail_branch`— y por la jerarquía de compañías.

### Las ACL no pueden recortar

`ir.model.access` es **aditiva**: las ACL de varios grupos se combinan con OR. Una ACL más
restrictiva para el perfil no recorta nada mientras `stock.group_stock_user` o
`point_of_sale.group_pos_user` sigan otorgando el permiso.

Por eso los cuatro huecos que dejan abiertos los grupos nativos se cierran con
**restricciones de registro por modo**, con un dominio que no matchea nada:

```
pos.config          write    → bloqueado
pos.order           unlink   → bloqueado
stock.picking.type  create   → bloqueado
pos.session         write/create → se dejan: los necesita la caja
```

Las ACL del CSV son redundantes con lo que ya dan los grupos implicados. Están igual, para
que la pestaña **Permisos** de la vista consolidada muestre el perfil completo.

### El costo va con `groups=`, no con la capa de presentación

`generic_security_restriction` oculta campos inyectando `invisible` en
`_postprocess_tag_field`: actúa sobre los nodos `<field>` de la vista. Eso es cosmética.

- No saca el campo de `fields_get`. En una vista **pivot** —y la Consulta de Stock lo
  es— el usuario abre el desplegable de Medidas y agrega el costo a mano.
- No impide un `read` por RPC, ni una exportación, ni un filtro.

El atributo `groups=` nativo sí: Odoo lo aplica en `fields_get` y en el `read` del ORM.

`standard_price` pasa de `groups="base.group_user"` a `group_product_cost`.

> **Radio cero en el deploy.** La instalación le otorga el grupo a todos los usuarios
> internos actuales **menos** los del perfil sucursal. El día del deploy no cambia nada
> para nadie; después se saca gente deliberadamente.
>
> **Consecuencia operativa:** un usuario interno creado *después* NO lo recibe solo. Hay
> que dárselo a mano o el costo le queda oculto. El grupo no lo implica nadie a propósito:
> si lo implicara `base.group_user` lo tendría todo el mundo, incluido el perfil sucursal,
> y no serviría de nada.

#### Asignar el perfil son DOS pasos, no uno

**Poner a alguien en el perfil Usuario Sucursal no le quita el grupo de costo.** Son grupos
independientes, y los grupos en Odoo solo suman.

Un usuario que ya existía cuando se instaló el módulo recibió `group_product_cost` por la
siembra de radio cero. Si después le asignás el perfil y no hacés nada más, **va a seguir
viendo el costo**, y todo lo demás del recorte va a funcionar igual — lo que hace fácil dar
por bueno un perfil que todavía filtra costos.

Para que el recorte de costo aplique hay que hacer las dos cosas:

1. Ficha del usuario → **FORUM / Perfil** → *Usuario Sucursal*
2. **Destildar** *Ver costo de productos* en la pestaña de permisos

Esto es lo que quiere decir "después se saca gente deliberadamente": la siembra monta el
mecanismo sin mover a nadie, y cada quita es una decisión explícita.

**Cómo verificarlo**, sin depender de mirar una pantalla:

```python
e = env(user=usuario)
'standard_price' in e['product.template'].fields_get()          # False si quedó bien
[c for c in ('value_report', 'management_cost', 'management_value', 'management_rate')
 if c in e['stock.quant.product.location.report'].fields_get()]  # [] si quedó bien
```

Si el campo sigue apareciendo en `fields_get`, el usuario conserva el grupo de costo.

### La Consulta de Stock: acción propia, no mutilada

El menú que existe apunta a la acción **"Costo por ubicación"**, en vista pivot. En vez de
mutilarla, el perfil tiene su propia acción en vista lista, con las columnas de
disponibilidad y ninguna de valor.

El perfil **ve** la Consulta de Stock —puede buscar un artículo y ver su disponibilidad por
local y por talle— **sin** costo ni margen.

## Convención de listas de precios

**Las listas de precios viven en la casa central o sin compañía, nunca dentro de la
compañía de una franquicia.**

Si hace falta una lista específica para un local de franquicia, se crea en FORUM y se le
asigna a su PDV.

El motivo es la dirección de la jerarquía: las reglas de core usan
`('company_id', 'parent_of', company_ids)`, que hace que **el hijo vea al padre**. Una
lista que pertenezca a la compañía de una franquicia no la ve la casa central.

La instalación archiva las listas vacías que Odoo crea automáticamente por compañía —sin
ítems, sin PDV y sin pedidos—, que son ruido. Cualquier lista con contenido queda intacta.

## Reglas que la instalación desarchiva

Solo dos, las de core:

- `product.product_pricelist_comp_rule`
- `product.product_pricelist_item_comp_rule`

Alguien las archivó para que un usuario de franquicia viera listas de la casa central. Con
la jerarquía de compañías declarada, el `parent_of` de su propio dominio ya lo resuelve.

Las reglas creadas a mano **no se tocan**: se reportan en el log para que alguien las
revise. Dos de ellas matchean el *apellido* del usuario contra el nombre del almacén, que
es la razón por la que no dejaban pasar nada.

## Por qué la migración vive en el hook

Un script de `migrations/` **no corre en la primera instalación**: Odoo solo lo ejecuta
cuando la versión instalada cambia. Para un módulo nuevo el único punto de entrada es
`post_init_hook`. `migrations/17.0.1.0.0/post-migrate.py` llama a la misma función, que es
idempotente.

La migración deriva el almacén de cada usuario por `pos_config.picking_type_id.warehouse_id`
a partir de `allowed_pos` (de `pos_restrict`). **Eso falla en las franquicias**, donde el
PDV y el almacén son de compañías distintas y `picking_type_id` no cruza esa frontera. Los
usuarios que no se pueden derivar quedan **listados en el log** para asignación manual.
