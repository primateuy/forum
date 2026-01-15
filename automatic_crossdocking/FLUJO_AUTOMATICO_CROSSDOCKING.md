# FLUJO AUTOMÁTICO DE CROSSDOCKING

## Resumen General

Cuando se confirma una orden de compra (PO) con **crossdocking habilitado**, el sistema ahora ejecuta automáticamente todo el flujo de distribución sin necesidad de intervención manual.

---

## Flujo Paso a Paso

### 1️⃣ **Confirmación de la Orden** (`button_confirm()`)
```
Usuario: Hace clic en "Confirmar"
           ↓
Sistema: Verifica si la orden tiene crossdocking habilitado
           ↓
Sistema: Si SÍ → Ejecuta el flujo de crossdocking automáticamente
```

### 2️⃣ **Validación de Líneas**
```
Sistema: Verifica que todas las líneas tengan el percentage correcto
         Si una línea NO tiene percentage → Asigna el del PO
         
Sistema: Solo procesa líneas con use_crossdock = True
         Las líneas sin crossdock se procesan de forma regular
```

### 3️⃣ **Creación de Recepción Principal** (`_create_main_reception_picking()`)
```
Ubicación Origen: Proveedores
              ↓
        Picking Type: Recepción Crossdocking (incoming)
              ↓
Ubicación Destino: Entrada del Almacén
```

**Resultado**: Un picking que recibe toda la mercadería en la ubicación de entrada.

---

### 4️⃣ **Cálculo de Distribución** (`_calculate_equitable_distribution()` o `_calculate_crossdock_distribution()`)

**Se calcula automáticamente:**
- Qué porcentaje va a crossdocking (línea_percentage × cantidad)
- Qué porcentaje va a existencias principales (100% - crossdocking)
- Cómo distribuir equitativamente entre almacenes

```
Línea: 100 unidades
Percentage: 80%
              ↓
Cantidad para Crossdocking: 80 unidades
Cantidad para Stock Principal: 20 unidades
```

---

### 5️⃣ **Creación de Pickings de Distribución**
```
Para cada ubicación de destino:
  ├─ Crea un Picking con tipo "Crossdocking"
  ├─ Origen: Entrada del Almacén
  ├─ Destino: Ubicación de Stock del Almacén
  └─ Movimientos: Se crean con las cantidades calculadas
```

---

### 6️⃣ **Establecimiento de Dependencias** (`_setup_picking_dependencies()`)
```
Flujo correcto:
  1. Recepción (entrada) ← primero
  2. Distribución (crossdocking) ← después (espera recepción)
  3. Stock (saldo) ← al final (opcional)
```

---

## Eventos Que Disparan el Flujo

### Automático:
1. ✅ **Confirmación de Orden** (`button_confirm()`)
   - Se ejecuta cuando el usuario confirma la orden
   - Verifica si tiene crossdocking
   - Crea automáticamente todos los pickings

2. ✅ **Creación de Picking** (`_create_picking()`)
   - Se ejecuta desde el modelo base de Odoo
   - Segmenta órdenes regulares vs crossdocking
   - Procesa cada una con su flujo correspondiente

### Manual:
3. ⚙️ **Activar Pickings** (`action_activate_crossdock_pickings()`)
   - El usuario puede activar manualmente pickings en estado "waiting"

---

## Estados de los Pickings

```
Recepción:
  draft → confirmed → assigned → done

Crossdocking:
  draft → confirmed → waiting → (espera recepción) → assigned → done

Stock Principal:
  draft → confirmed → waiting → assigned → done
```

---

## Campos Clave en Línea de Compra

| Campo | Obligatorio | Descripción |
|-------|-------------|-------------|
| `use_crossdock` | Sí | Habilita/deshabilita crossdocking en la línea |
| `line_crossdock_percentage` | No | % para crossdocking (0-1). Si no tiene, usa el del PO |
| `distribution_multiple` | No | Múltiplo de redondeo |

---

## Campos Clave en Orden de Compra

| Campo | Obligatorio | Descripción |
|-------|-------------|-------------|
| `crossdock_enabled` | Sí | Habilita crossdocking en toda la orden |
| `crossdock_percentage` | Sí | % por defecto para todas las líneas (0-100) |
| `distribution_rounding_method` | No | Cómo redondear (nearest, floor, ceil) |

---

## Manejo de Errores

```
Si ocurre error:
  ├─ Se registra en los logs del servidor
  ├─ Se publica un mensaje en el chatter de la orden
  ├─ Se continúa con la siguiente orden
  └─ No afecta el resto del proceso
```

---

## Ejemplo Práctico

### Escenario:
- **Orden de Compra**: PO-001
- **Crossdocking**: Habilitado, 80%
- **Línea**: 100 unidades de Producto A
- **Almacenes destino**: Almacén 1, Almacén 2 (equitativo)

### Resultado:

**Paso 1 - Recepción:**
```
Picking: REC/PO-001
  100 unidades → Entrada del Almacén (Centro Logístico)
```

**Paso 2 - Distribución Crossdocking (80 unidades):**
```
Picking CROSS-001:
  40 unidades → Stock Almacén 1
  40 unidades → Stock Almacén 2

Picking CROSS-002:
  20 unidades → Stock Principal (Centro Logístico)
```

**Paso 3 - Trazabilidad:**
- Entrada de mercadería (Recepción)
- Salida hacia cada almacén (Crossdocking)
- Movimientos rastreables en el historial

---

## Diagnóstico de Problemas

### ❌ Los pickings NO se crean al confirmar

**Posibles causas:**
1. Orden NO tiene `crossdock_enabled = True`
2. Líneas NO tienen `use_crossdock = True`
3. El tipo de orden NO tiene crossdocking configurado
4. Error en la ejecución (revisar logs)

**Solución:**
```
1. Verificar que la orden tenga crossdocking
2. Verificar que las líneas tengan use_crossdock = True
3. Revisar logs: /var/log/odoo/odoo.log
```

### ❌ Los pickings se crean pero los movimientos NO se confirman

**Posibles causas:**
1. Ubicación de entrada no existe
2. Tipo de operación no configurado
3. Falta de permisos de usuario

**Solución:**
```
1. Verificar ubicaciones en el almacén
2. Verificar tipos de operación
3. Activar manualmente con "Activar Pickings de Crossdocking"
```

### ⚠️ Hay exceso en la distribución

**Significado:** La suma de cantidades distribuidas supera la cantidad esperada

**Causa:** Redondeo de múltiplos generó más cantidad

**Solución:**
```
Sistema ajusta automáticamente:
  - Reduce el principal si es necesario
  - Marca la orden con bandera "exceso"
  - Publica mensaje de advertencia
```

---

## Integración con Rutas

Una vez los pickings están creados, las **Rutas Estándar de Odoo** pueden:

1. ✅ Crear movimientos de entrada en cada almacén
2. ✅ Generar órdenes de trabajo automáticas
3. ✅ Sincronizar con sistemas de logística
4. ✅ Crear trazabilidad completa

---

## Resumen de Cambios en Código

### `button_confirm()`
- ✅ Ahora ejecuta la distribución crossdocking automáticamente
- ✅ Valida percentages antes de procesar
- ✅ Publica mensajes de éxito/error
- ✅ Manejo robusto de excepciones

### `_create_picking()`
- ✅ Mejorado con mejor documentación
- ✅ Añadido manejo de errores
- ✅ Segmentación clara de flujos (regular vs crossdocking)

### Stock Warehouse (PUNTO 1)
- ✅ Ubicación Crossdocking automática
- ✅ Tipos de operación configurables
- ✅ Estructura flexible para rutas

