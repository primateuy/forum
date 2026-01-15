# FLUJO DE CROSSDOCKING EN 3 PASOS

## 📊 Arquitectura del Flujo Implementado

El sistema ahora ejecuta un flujo completo de **3 pasos** que crea **trazabilidad completa** de la mercadería desde el Centro Logístico hasta el Stock final del Almacén.

---

## 🎯 Los 3 Pasos del Flujo

### **PASO 1: RECEPCIÓN** 
```
Proveedor → Centro Logístico (Entrada)
```

**Qué ocurre:**
- Se crea un **Picking de Recepción**
- Tipo: `Recepción Crossdocking` (incoming)
- Origen: Proveedores
- Destino: **Entrada del Almacén Principal**
- Estado: `assigned`

**Ejemplo:**
```
Picking: REC-001
  100 unidades Producto A
  de: Proveedores
  a: Centro Logístico/Entrada
  estado: assigned ✓ (listo para recibir)
```

---

### **PASO 2: DISTRIBUCIÓN A UBICACIÓN CROSSDOCKING**
```
Centro Logístico (Entrada) → Almacenes Destino (Ubicación Crossdocking)
```

**Qué ocurre:**
- Se crea un **Picking de Crossdocking** por cada almacén destino
- Tipo: `Crossdocking` (internal)
- Origen: Entrada del Almacén Principal
- Destino: **Ubicación Crossdocking del Almacén Destino** ← ¡AQUÍ ESTÁ LA NOVEDAD!
- Estado: `waiting` (espera a que termine la recepción)

**Dependencia:** Este picking **depende** del PASO 1. No se inicia hasta que la mercadería está en Entrada.

**Ejemplo:**
```
Picking: CD-001 (Centro Logístico → Almacén 1)
  40 unidades Producto A
  de: Centro Logístico/Entrada
  a: Almacén 1/Ubicación Crossdocking  ← Punto intermedio
  estado: waiting (esperando recepción)
  
Picking: CD-002 (Centro Logístico → Almacén 2)
  40 unidades Producto A
  de: Centro Logístico/Entrada
  a: Almacén 2/Ubicación Crossdocking  ← Punto intermedio
  estado: waiting (esperando recepción)
```

---

### **PASO 3: DISTRIBUCIÓN FINAL A STOCK**
```
Almacenes Destino (Ubicación Crossdocking) → Almacenes Destino (Stock)
```

**Qué ocurre:**
- Se crea un **Picking Final** por cada almacén
- Tipo: Operación interna del almacén
- Origen: **Ubicación Crossdocking del Almacén**
- Destino: **Stock del Almacén** (lot_stock_id)
- Estado: `waiting` (espera a que termine PASO 2)

**Dependencia:** Este picking **depende** del PASO 2. No se inicia hasta que la mercadería está en ubicación crossdocking.

**Ejemplo:**
```
Picking: FIN-001 (Almacén 1: Crossdocking → Stock)
  40 unidades Producto A
  de: Almacén 1/Ubicación Crossdocking
  a: Almacén 1/Stock
  estado: waiting (esperando crossdocking)

Picking: FIN-002 (Almacén 2: Crossdocking → Stock)
  40 unidades Producto A
  de: Almacén 2/Ubicación Crossdocking
  a: Almacén 2/Stock
  estado: waiting (esperando crossdocking)

Picking: FIN-003 (Centro Logístico: Principal → Stock)
  20 unidades Producto A
  de: Centro Logístico/Entrada
  a: Centro Logístico/Stock
  estado: waiting
```

---

## 🔄 Flujo Visual Completo

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         ORDEN DE COMPRA (PO-001)                        │
│                      100 unidades, 80% Crossdocking                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                    PASO 1: RECEPCIÓN (Picking REC-001)                  │
│  Proveedor ──→ Centro Logístico/Entrada (100 unidades)                 │
│  Estado: assigned ✓ (Listo para recibir)                               │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
                        (Mercadería ingresa)
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│            PASO 2A: DISTRIBUCIÓN 80% a Almacenes (Picking CD-001)      │
│  Centro Logístico/Entrada ──→ Almacén 1/Crossdocking (40 unidades)    │
│  Estado: waiting (espera a PASO 1)                                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│            PASO 2B: DISTRIBUCIÓN 80% a Almacenes (Picking CD-002)      │
│  Centro Logístico/Entrada ──→ Almacén 2/Crossdocking (40 unidades)    │
│  Estado: waiting (espera a PASO 1)                                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
                    (Pickings se activan automáticamente)
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│          PASO 3A: FINAL al Stock (Picking FIN-001)                     │
│  Almacén 1/Crossdocking ──→ Almacén 1/Stock (40 unidades)             │
│  Estado: waiting (espera a PASO 2A)                                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│          PASO 3B: FINAL al Stock (Picking FIN-002)                     │
│  Almacén 2/Crossdocking ──→ Almacén 2/Stock (40 unidades)             │
│  Estado: waiting (espera a PASO 2B)                                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│   PASO 3C: STOCK PRINCIPAL (Picking FIN-003)                            │
│  Centro Logístico/Entrada ──→ Centro Logístico/Stock (20 unidades)    │
│  Estado: waiting                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
                           ✓ PROCESO COMPLETO
```

---

## 📋 Campos y Configuración Necesaria

### En cada **Almacén**:

```
Almacén
├── crossdocking_location_id
│   └── Se crea automáticamente como ubicación de tránsito hija de 
│       "Transferencia de Almacenes"
│
├── crossdocking_type_id
│   └── Tipo de operación "Crossdocking" (internal)
│       - Origen: crossdocking_location_id
│       - Destino: en blanco (se asigna dinámicamente)
│
└── crossdocking_reception_type_id
    └── Tipo de operación "Recepción Crossdocking" (incoming)
        - Origen: Proveedores
        - Destino: crossdocking_location_id
```

---

## 🔧 Métodos Principales Involucrados

### `button_confirm()` - Punto de entrada
- Se ejecuta cuando confirmas la orden
- Valida que exista distribución crossdocking
- Llama a `_create_picking()`

### `_create_picking()` - Orquestador principal
1. Crea PASO 1 con `_create_main_reception_picking()`
2. Crea PASO 2 con `_create_equitable_distribution_pickings()` o similar
3. Crea PASO 3 con `_create_final_distribution_pickings()` ← **NUEVA**
4. Establece dependencias con `_setup_picking_dependencies()` ← **MEJORADA**

### `_create_final_distribution_pickings()` - NUEVO
- Crea pickings que van desde ubicación crossdocking → stock final
- Recibe la distribución calculada
- Por cada almacén crea un picking independiente

### `_setup_picking_dependencies()` - MEJORADO
- Ahora maneja **3 niveles de dependencia**:
  1. PASO 2 depende de PASO 1
  2. PASO 3 depende de PASO 2
  3. Conecta los movimientos por producto

---

## ✅ Ventajas de este Flujo

### 1. **Trazabilidad Completa**
```
Puedes rastrear cada paquete en:
  - Centro Logístico/Entrada (en tránsito)
  - Almacén/Crossdocking (recibido, en tránsito)
  - Almacén/Stock (entregado)
```

### 2. **Flexibilidad Operativa**
```
En la ubicación crossdocking puedes:
  - Hacer inspecciones
  - Separar por transportista
  - Cambiar destino si es necesario
  - Hacer ajustes de calidad
```

### 3. **Integración con Rutas Odoo**
```
Las rutas estándar pueden:
  - Crear automáticamente órdenes de trabajo
  - Sincronizar con sistemas de logística
  - Crear movimientos adicionales si es necesario
```

### 4. **Auditoría**
```
Cada paso queda registrado:
  - Quién movió la mercadería
  - Cuándo
  - De dónde a dónde
  - En qué almacén quedó
```

---

## 🚀 Estados y Transiciones

```
PASO 1 (Recepción):
  draft → confirmed → assigned ✓

PASO 2 (Crossdocking):
  draft → confirmed → waiting (espera P1) → assigned ✓

PASO 3 (Final):
  draft → confirmed → waiting (espera P2) → assigned ✓
```

---

## 📝 Ejemplo Real Paso a Paso

### Orden Original
```
PO-001: 
  Producto Laptop
  Cantidad: 100 unidades
  Crossdocking: Habilitado, 80%
  Almacenes destino: Almacén Buenos Aires, Almacén Córdoba
```

### Sistema Genera Automáticamente

**Paso 1 - Recepción (REC-001):**
```
De: Proveedores Internacionales
A: Centro Logístico/Entrada
Cantidad: 100 laptops
Usuario: (quien confirma la orden)
Fecha: 06-01-2026
Estado: assigned (recibido) ✓
```

**Paso 2a - Crossdocking a Buenos Aires (CD-001):**
```
De: Centro Logístico/Entrada
A: Almacén Buenos Aires/Crossdocking
Cantidad: 40 laptops (80% ÷ 2)
Depende de: REC-001
Estado: waiting → assigned (cuando llega mercadería) ✓
```

**Paso 2b - Crossdocking a Córdoba (CD-002):**
```
De: Centro Logístico/Entrada
A: Almacén Córdoba/Crossdocking
Cantidad: 40 laptops (80% ÷ 2)
Depende de: REC-001
Estado: waiting → assigned ✓
```

**Paso 3a - Final Buenos Aires (FIN-001):**
```
De: Almacén Buenos Aires/Crossdocking
A: Almacén Buenos Aires/Stock
Cantidad: 40 laptops
Depende de: CD-001
Estado: waiting → assigned ✓
```

**Paso 3b - Final Córdoba (FIN-002):**
```
De: Almacén Córdoba/Crossdocking
A: Almacén Córdoba/Stock
Cantidad: 40 laptops
Depende de: CD-002
Estado: waiting → assigned ✓
```

**Paso 3c - Stock Principal (FIN-003):**
```
De: Centro Logístico/Entrada
A: Centro Logístico/Stock
Cantidad: 20 laptops (20% que no se distribuye)
Estado: waiting → assigned ✓
```

---

## 🔍 Validación

Para verificar que el flujo funciona:

1. Crear una orden con crossdocking
2. Confirmar la orden
3. Ir a "Envíos" (Stock → Movimientos → Envíos)
4. Verificar que existan 5 pickings (1 recepción + 2 crossdocking + 2 finales)
5. Verificar que los estados sean: assigned, waiting, waiting, etc.
6. Verificar las dependencias (icono de cadena entre pickings)

