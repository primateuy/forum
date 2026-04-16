# Analisis y plan para el caso de automatismo entre `pricelist_change` y `fixed_price`

## Caso reportado

Escenario observado en POS:

1. Se agregan 2 medias y se activa su `fixed_price`.
2. Se agregan 2 boxers y se activa su `fixed_price`.
3. Se agregan 2 shorts y se activa la promo `2x`, que usa `pricelist_change`.

Problema:

- al activarse automaticamente la promo `2x`, se desactivan las promos anteriores de medias y boxers;
- sin embargo, si luego se toca manualmente el boton de lista de precios y se vuelve a seleccionar la misma promo `2x`, las promos de medias y boxers vuelven a aplicarse correctamente;
- la promo `2x` sobre los shorts se mantiene.

## Lectura tecnica del sintoma

Esto indica que:

- las condiciones de elegibilidad de las promos `fixed_price` siguen cumpliendose;
- el problema no parece estar en la definicion de reglas o rewards;
- el fallo esta en la secuencia automatica de aplicacion cuando entra en juego `pricelist_change`.

En otras palabras:

- manualmente funciona;
- automaticamente no se reevalua bien todo el conjunto de recompensas.

## Codigo relevante

Archivo principal:

- [pricelistReward.js](E:\Odoo_Primate\addons\cambio_precio\static\src\js\pricelistReward.js)

### Punto critico 1: aplicacion automatica de `pricelist_change`

En `_applyCustomRewardsOnly()` hoy ocurre esto:

```js
if (cumple) {
    const targetPricelistId = pricelistReward.reward.discount_max_amount;
    const targetPricelist = this.pos.pricelists.find(p => p.id === targetPricelistId);
    if (targetPricelist && (!this.pricelist || this.pricelist.id !== targetPricelistId)) {
        this._restoringPricelist = true;
        this.set_pricelist(targetPricelist);
        this._restoringPricelist = false;
        if (typeof this._resetTaxesAndPrices === 'function') this._resetTaxesAndPrices();
    }
}
```

### Punto critico 2: re-evaluacion al cambiar pricelist

En `set_pricelist(pricelist)` hoy ocurre esto:

```js
set_pricelist(pricelist) {
    super.set_pricelist(...arguments);
    if (!this._restoringPricelist) {
        debouncedUpdateRewards(this, 150);
    }
}
```

## Hipotesis principal

La causa mas probable es esta:

- cuando la promo `2x` se aplica automaticamente, el codigo hace `set_pricelist(...)` con `_restoringPricelist = true`;
- esa bandera bloquea el `debouncedUpdateRewards(...)` que normalmente reevalua las rewards custom;
- ademas, luego se llama a `_resetTaxesAndPrices()`, que probablemente pisa los precios especiales ya aplicados;
- como no se dispara una nueva re-evaluacion de recompensas despues de ese reset, las promos `fixed_price` quedan apagadas.

Esto encaja muy bien con el comportamiento observado, porque:

- cuando vos tocás manualmente el boton de lista de precios, `set_pricelist(...)` corre sin `_restoringPricelist = true`;
- por lo tanto si dispara `debouncedUpdateRewards(...)`;
- y en esa segunda pasada vuelven a aplicarse las promos `fixed_price`.

## Conclusión del analisis

La falla parece ser de automatismo y de orden de ejecucion, no de reglas de negocio.

Mas concretamente:

- el flujo automatico de `pricelist_change` no deja una re-evaluacion final de las promos `fixed_price` luego del cambio de lista y del reseteo de precios/impuestos.

## Plan propuesto

### 1. Mantener la logica de elegibilidad actual

No cambiar reglas, rewards ni condiciones de negocio.

Objetivo:

- corregir solo el automatismo.

### 2. Ajustar la secuencia despues de aplicar `pricelist_change`

Luego de hacer:

- `set_pricelist(targetPricelist)`
- `_resetTaxesAndPrices()`

forzar una nueva re-evaluacion de recompensas custom.

Objetivo:

- que el cambio de lista no deje apagadas las promos `fixed_price` ya elegibles.

### 3. Evitar recursion o loops

El ajuste debe respetar el motivo original de `_restoringPricelist`, que claramente fue introducido para evitar recursiones al cambiar la lista desde codigo.

Objetivo:

- reactivar la re-evaluacion final sin generar un loop infinito entre `set_pricelist()` y `_applyCustomRewardsOnly()`.

### 4. Probar especificamente la secuencia combinada

Escenario minimo a validar:

1. Agregar 2 medias.
2. Agregar 2 boxers.
3. Agregar 2 shorts.

Resultado esperado:

- shorts con promo `2x` via `pricelist_change`;
- medias mantienen `fixed_price`;
- boxers mantienen `fixed_price`;
- sin tocar manualmente el boton de lista de precios.

### 5. Probar ida y vuelta

Tambien validar:

- agregar los shorts y activar el `2x`;
- luego quitar los shorts;
- verificar que la lista de precios se restaure bien;
- y que medias/boxers sigan con su comportamiento correcto.

Objetivo:

- asegurar que el fix no rompa la restauracion automatica.

## Alcance estimado

Cambio principal:

- [pricelistReward.js](E:\Odoo_Primate\addons\cambio_precio\static\src\js\pricelistReward.js)

En principio no parece necesario:

- tocar Python;
- tocar vistas;
- tocar seguridad.

## Resumen corto

La hipotesis mas fuerte es:

- el flujo automatico de `pricelist_change` cambia la lista y resetea precios, pero no ejecuta una re-evaluacion final de las promos `fixed_price`;
- el cambio manual de lista si provoca esa re-evaluacion, por eso "arregla" el estado.

No se realizaron cambios de codigo en este analisis.
