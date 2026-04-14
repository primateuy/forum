# Analisis y plan para promociones simultaneas de precio fijo

## Caso reportado

Existen dos promociones configuradas en POS:

- Promo medias: al seleccionar 2 productos de medias, cada producto queda con precio fijo de `$150`.
- Promo boxer: al seleccionar 2 productos de boxer, cada producto queda con precio fijo de `$295`.

Comportamiento actual:

- Si la orden tiene solo medias, funciona correctamente.
- Si la orden tiene solo boxers, funciona correctamente.
- Si la orden tiene 2 medias y 2 boxers al mismo tiempo, solo se aplica la promo al primer grupo detectado y el otro grupo queda sin promo.

Comportamiento esperado:

- En una misma orden se deben aplicar ambas promociones en paralelo.
- El par de medias debe recibir su precio fijo y el par de boxers tambien.

## Diagnostico validado contra el codigo actual

El problema esta en el frontend del POS, en:

- [pricelistReward.js](E:\Odoo_Primate\addons\cambio_precio\static\src\js\pricelistReward.js)

Puntualmente en:

- `_applyCustomRewardsOnly()`

### Hallazgo principal confirmado

La logica actual toma solo una recompensa `fixed_price` usando `find(...)`:

```js
const fixedPriceReward = claimable.find(
    r => r.reward && r.reward.reward_type === "fixed_price"
);
```

Eso implica que:

- si hay varias recompensas `fixed_price` reclamables, el codigo usa solo la primera;
- las demas no se evalúan ni se aplican.

Eso coincide exactamente con el bug reportado.

## Ajuste importante al analisis original

El backend exporta estructuras mas ricas:

- `fixed_price_data`
- `fixed_price_map`

desde:

- [models.py](E:\Odoo_Primate\addons\cambio_precio\models\models.py)

Pero la configuracion visible actual del reward en vista no esta usando `fixed_price_line_ids` como flujo principal. En este momento, en:

- [views.xml](E:\Odoo_Primate\addons\cambio_precio\views\views.xml)

el bloque de `fixed_price_line_ids` esta comentado y quedo visible:

```xml
<field name="fixed_price" invisible="reward_type != 'fixed_price'"/>
```

O sea:

- el caso real hoy parece apoyarse principalmente en `reward.fixed_price`;
- el bug actual no exige cambiar backend para ser resuelto.

## Conclusión

La causa mas probable es:

- la implementacion actual fue escrita para aplicar una sola recompensa `fixed_price` por vez.

Por eso la correccion debe concentrarse primero en el JavaScript del POS.

## Plan actualizado

### 1. Procesar todas las recompensas `fixed_price` reclamables

Refactorizar `_applyCustomRewardsOnly()` para reemplazar el `find(...)` por una iteracion sobre todas las recompensas `fixed_price` activas.

Objetivo:

- permitir multiples promociones `fixed_price` simultaneas dentro de la misma orden.

### 2. Resolver la recompensa correcta por linea

Para cada linea de la orden:

- evaluar todas las rewards `fixed_price` activas;
- aplicar solo la primera reward que matchee esa linea.

Objetivo:

- que medias reciba la promo de medias y boxer reciba la promo de boxer en la misma orden.

### 3. Restaurar precios desde una base limpia

Mantener y usar el precio original de cada linea antes de aplicar una reward custom.

Objetivo:

- evitar precios pegados cuando cambian cantidades, productos o condiciones.

### 4. Limpiar labels y metadatos por linea

Guardar en cada linea que reward custom fue aplicada y limpiar esa informacion si la linea deja de calificar.

Objetivo:

- restaurar correctamente precios y badges sin dejar residuos visuales o funcionales.

### 5. Mantener compatibilidad con la estructura existente

La implementacion debe seguir funcionando con el flujo actual basado en:

- `reward.fixed_price`

y, de forma compatible, poder aprovechar:

- `fixed_price_map`
- `fixed_price_data`

si ya vienen cargados.

Objetivo:

- resolver el bug actual sin romper configuraciones existentes ni cerrar la puerta a configuraciones mas especificas.

### 6. Validacion manual en POS

Probar al menos estos escenarios:

- 2 medias
- 2 boxers
- 2 medias + 2 boxers
- 1 media + 2 boxers
- 2 medias + 1 boxer
- agregar y quitar lineas despues de aplicar la promo

Objetivo:

- verificar aplicacion correcta y restauracion correcta.

## Riesgo adicional detectado

Hay un riesgo latente que conviene considerar durante la implementacion:

- si una promo de "2 productos" hoy se evalua solo por dominio y luego aplica precio fijo a todas las lineas que matchean, podria existir un caso futuro donde mas de dos productos reciban el beneficio.

Ese punto no invalida el diagnostico principal, pero debe revisarse durante la prueba funcional.

## Criterio propuesto para conflictos

Si una misma linea llegara a calificar para mas de una promo `fixed_price` al mismo tiempo:

- aplicar una sola promo por linea;
- priorizar la primera recompensa reclamable devuelta por Odoo.

## Alcance estimado

Cambio principal:

- [pricelistReward.js](E:\Odoo_Primate\addons\cambio_precio\static\src\js\pricelistReward.js)

En principio:

- no hace falta modificar Python para este bug;
- no hace falta tocar seguridad;
- no hace falta cambiar vistas para corregir el caso reportado.

## Resumen

El diagnostico principal queda confirmado:

- el bug ocurre porque el POS procesa solo la primera recompensa `fixed_price` activa.

La solucion propuesta es hacer que el frontend procese multiples rewards `fixed_price` simultaneas y administre correctamente precio original, reward aplicada y limpieza por linea.
