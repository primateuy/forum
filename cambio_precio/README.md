# Cambio de Precio Safe

Esta versión elimina la intervención sobre el flujo estándar de loyalty de Odoo POS.

## Cambios principales
- No toca `coupon_point_changes`
- No parchea `push_single_order()`
- No parchea `_updateRewards()`
- No modifica `export_as_JSON()` para la estructura estándar de loyalty

## Mantiene
- Recompensa `pricelist_change`
- Recompensa `fixed_price`
- Badge visual en líneas de POS para precio fijo

## Limitación
Estas recompensas custom se aplican desde el botón de recompensas y no interfieren con el cálculo nativo de puntos/cupones.
