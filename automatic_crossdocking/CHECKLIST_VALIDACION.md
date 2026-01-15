# CHECKLIST DE VALIDACIÓN - FLUJO AUTOMÁTICO CROSSDOCKING

## Pre-Requisitos (Antes de Confirmar Orden)

### ✅ Configuración en el Almacén Principal
- [ ] Almacén tiene ubicación de Crossdocking creada
- [ ] Almacén tiene "Tipo de Operación: Recepción Crossdocking"
- [ ] Almacén tiene "Tipo de Operación: Crossdocking"
- [ ] Almacén tiene ubicación WH/Entrada configurada

### ✅ Configuración del Tipo de Orden
- [ ] Tipo de Orden tiene "Crossdock habilitado" = True
- [ ] Tipo de Orden tiene porcentaje por defecto (ej: 80%)
- [ ] Tipo de Orden tiene método de redondeo seleccionado

### ✅ Configuración de la Orden
- [ ] Orden de Compra tiene "Crossdock habilitado" = True
- [ ] Orden tiene porcentaje configurado (ej: 80%)
- [ ] Orden tiene método de redondeo configurado

### ✅ Configuración de Líneas
- [ ] Cada línea tiene "use_crossdock" = True
- [ ] Cada línea tiene porcentaje (o usa el de la orden)
- [ ] Las líneas son de productos tangibles (product, consu)

---

## Proceso de Confirmación

### 1️⃣ Antes de Confirmar
```
[ ] Verificar que todo en "Pre-Requisitos" esté listo
[ ] Revisar cantidades en las líneas
[ ] Confirmar que el tipo de orden es correcto
```

### 2️⃣ Confirmar la Orden
```
[ ] Hacer clic en "Confirmar" en la PO
[ ] Sistema debería ejecutarse automáticamente
[ ] No debería haber errores en el proceso
```

### 3️⃣ Validar Resultados en la Orden
```
[ ] Orden está en estado "Compra" o "Hecha"
[ ] Chatter muestra: "✓ Distribución crossdocking creada automáticamente"
[ ] No hay mensajes de error
```

---

## Validación de Pickings Creados

### ✅ Recepción Principal
```
[ ] Existe 1 picking con origen "Recepción Crossdocking"
[ ] Picking tiene estado "draft" o "confirmed"
[ ] Todos los movimientos están presentes
[ ] Ubicación destino = Entrada del Almacén
```

### ✅ Pickings de Distribución
```
[ ] Se creó 1 picking por cada ubicación de destino
[ ] Cada picking tiene origen "Crossdocking"
[ ] Estado: "waiting" (esperando recepción)
[ ] Movimientos tienen cantidades correctas
```

### ✅ Pickings Regulares (si hay líneas sin crossdock)
```
[ ] Se creó 1 picking regular
[ ] Contiene solo líneas sin use_crossdock
[ ] Ubicación destino = Stock regular
```

---

## Validación de Movimientos

### ✅ Recepción (Pickup Principal)
```
Verificar en pestaña "Movimientos":
  [ ] Producto correcto
  [ ] Cantidad = suma de todas las líneas
  [ ] Ubicación origen = Proveedores
  [ ] Ubicación destino = Entrada
  [ ] Estado = confirmed
```

### ✅ Distribución (Crossdocking)
```
Verificar en pickings de crossdocking:
  [ ] Movimientos están divididos por almacén destino
  [ ] Cantidades respetan el porcentaje configurado
  [ ] Ubicación origen = Entrada
  [ ] Ubicación destino = Stock del almacén
  [ ] Estado = waiting (esperando recepción)
```

---

## Pruebas Funcionales

### Test Case 1: Orden Simple Crossdocking
```
Escenario:
  - Producto A: 100 unidades, 80% crossdock
  - 1 almacén destino
  
Resultado esperado:
  - Recepción: 100 unidades → Entrada
  - Crossdocking: 80 unidades → Stock Almacén
  - Stock Principal: 20 unidades → Stock Principal
```

**Pasos:**
1. [ ] Crear orden con estas líneas
2. [ ] Confirmar orden
3. [ ] Validar pickings creados
4. [ ] Confirmar que no hay errores

---

### Test Case 2: Múltiples Almacenes (Equitativo)
```
Escenario:
  - Producto B: 100 unidades, 80% crossdock
  - 2 almacenes destino (equitativo)
  
Resultado esperado:
  - Recepción: 100 unidades → Entrada
  - Crossdocking Almacén 1: 40 unidades
  - Crossdocking Almacén 2: 40 unidades
  - Stock Principal: 20 unidades
```

**Pasos:**
1. [ ] Crear orden con estas líneas
2. [ ] Confirmar orden
3. [ ] Validar distribución equitativa
4. [ ] Confirmar que no hay errores

---

### Test Case 3: Líneas Mixtas
```
Escenario:
  - Línea 1: Producto A (100u), use_crossdock = True, 80%
  - Línea 2: Producto B (50u), use_crossdock = False
  
Resultado esperado:
  - Recepción Crossdocking: 100u → Entrada
  - Crossdocking: 80u → Almacén
  - Picking Regular: 50u → Stock regular
  - Stock Principal: 20u → Stock
```

**Pasos:**
1. [ ] Crear orden con líneas mixtas
2. [ ] Confirmar orden
3. [ ] Validar que hay 2+ pickings
4. [ ] Validar que cada línea fue procesada correctamente

---

## Validación de Dependencias

```
[ ] Recepción está en estado "assigned"
[ ] Crossdocking está en estado "waiting"
[ ] Los moves de crossdocking esperan a la recepción
[ ] Después de confirmar recepción, crossdocking se activa
```

---

## Diagnóstico en Caso de Fallo

Si algo no funciona, verificar en este orden:

### 1. Revisar Logs
```bash
tail -f /var/log/odoo/odoo.log | grep "Error\|Exception\|crossdock"
```

### 2. Verificar Chatter
```
Ir a la Orden → pestaña "Historial"
Buscar mensajes de error o advertencias
```

### 3. Verificar Estructura del Almacén
```
Almacén → pestaña "Configuración Crossdocking"
  [ ] crossdocking_location_id tiene valor
  [ ] crossdocking_reception_type_id tiene valor
  [ ] crossdocking_type_id tiene valor
```

### 4. Verificar Tipo de Orden
```
Tipo de Orden → "Configuración Crossdocking"
  [ ] crossdock_enabled = True
  [ ] crossdock_percentage > 0
```

### 5. Habilitar Debug
```python
# En el código, agregar:
import logging
_logger = logging.getLogger(__name__)

# Antes de crear pickings:
_logger.info(f"DEBUG: Creando pickings para {order.name}")
_logger.info(f"DEBUG: Líneas crossdock: {lineas_crossdock}")
```

---

## Checklist Final

```
[ ] Documentación completada
[ ] Código mejorado y testeado
[ ] Flujo automático funcional
[ ] Manejo de errores robusto
[ ] Mensajes al usuario claros
[ ] Logs adecuados para debugging
```

