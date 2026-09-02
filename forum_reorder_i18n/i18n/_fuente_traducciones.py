# -*- coding: utf-8 -*-
"""Traducciones es_UY para los modulos de reordenamiento.

Glosario:
  Inter Company/Intercompany -> Inter-Compania    Requestor -> Solicitante
  Inter Warehouse            -> Inter-Almacen     Fulfiller -> Abastecedor
  ICT / IWT                  -> siglas, se dejan  Replenishment -> Reposicion
"""

# --- Correcciones de terminos ya traducidos (mal) en la base -------------------
CORRECCIONES = {
    'Settings - Advance Reordering': 'Configuración - Reordenamiento avanzado',
    'Inter Company Channel': 'Canal Inter-Compañía',
    'Inter Warehouse Channel': 'Canal Inter-Almacén',
    'Auto Workflow - ICT': 'Flujo automático - ICT',
    'Create / Update Reordering Rule': 'Crear / Actualizar regla de reordenamiento',
    'Reorder with Real Demand': 'Reordenar por demanda real',
    'Reorder with Real Demand planner': 'Planificador de reordenamiento por demanda real',
    'Reorder with Real Demand Auto Workflow':
        'Flujo automático de reordenamiento por demanda real',
    'Warehouse Group': 'Grupos de almacenes',
    'Inter Company Transaction': 'Transacciones Inter-Compañía',
    'Inter Company Transfer': 'Transferencia Inter-Compañía',
    'Inter Warehouse Transfer': 'Transferencia Inter-Almacén',
    'Reverse Transfer': 'Transferencia inversa',
    'Reordering with Order Points': 'Reglas de reordenamiento',
    'Import / Export Sales Forecast': 'Importar / Exportar pronóstico de ventas',
    'Forecast vs Actual Sales': 'Pronóstico vs. ventas reales',
    # Traduccion automatica con errores groseros, encontrados al revisar la base:
    # Pestana del proceso de reposicion. Estaba como "No se encuentra la venta de
    # pronostico", que se lee como un mensaje de error y no como el nombre de una pestana.
    'Not Found Forecast Sale': 'Sin pronóstico de ventas',
    'ID': 'ID',                        # estaba como "IDENTIFICACIÓN"
    'Pricelist': 'Lista de Precios',   # estaba como "Prficelista", con typo

    # "lead" traducido como el metal: "Dias de plomo". Aparece en toda la pantalla de
    # Reposicion de Almacenes y en la configuracion del reordenamiento.
    'Lead Days': 'Días de Plazo',
    'Lead days': 'Días de plazo',
    'Extra Percentage For Max Lead Days':
        'Porcentaje adicional sobre el plazo máximo',
    'Max lead days calculation Method': 'Método de cálculo del plazo máximo',
    'Vendor Static Lead Days': 'Días de Plazo Fijos del Proveedor',
    'Vendor lead days calculation Method':
        'Método de cálculo del plazo del proveedor',
    'Purchase lead calculation base on': 'Base de cálculo del plazo de compra',
    # ICT es la sigla de Inter Company Transfer, no "TIC"
    'ICT count': 'Cantidad de ICT',
    'Inter company channel': 'Canal inter-compañía',
    'Inter warehouse channel': 'Canal inter-almacén',
    # Siglas de clasificacion que quedaron con mayusculas de oracion
    'FSN-XYZ': 'FSN-XYZ',
    'XYZ': 'XYZ',
    'Is Order MOQ ?': '¿Respeta el mínimo de compra?',
    # Ingles crudo que quedo dentro de la traduccion
    'Advance Reorder Non Product Forecast':
        'Pronóstico de reordenamiento sin producto',
    'Min order amount': 'Importe mínimo del pedido',
    'PO Qty': 'Cantidad de la OC',
    'Product UOM': 'Unidad de Medida del Producto',
}

# --- Terminos sin traducir (fuente en ingles) --------------------------------
NUEVAS = {
    # setu_intercompany_transaction - canal
    'Advance Configurations': 'Configuración Avanzada',
    'Common Configurations': 'Configuración General',
    'Fulfiller': 'Abastecedor',
    'Fulfiller Company': 'Compañía Abastecedora',
    'Fulfiller Partner': 'Contacto Abastecedor',
    'Fulfiller Warehouse': 'Almacén Abastecedor',
    'Requestor': 'Solicitante',
    'Requestor Company': 'Compañía Solicitante',
    'Requestor Partner': 'Contacto Solicitante',
    'Requestor Warehouse': 'Almacén Solicitante',
    'Inter Company User': 'Usuario Inter-Compañía',
    'Customer Invoice Journal': 'Diario de Facturas de Cliente',
    'Vendor Bill Journal': 'Diario de Facturas de Proveedor',
    'Purchase Fiscal Position': 'Posición Fiscal de Compra',
    'Sales Fiscal Position': 'Posición Fiscal de Venta',
    'select fiscal position for purchase order':
        'Posición fiscal a usar en la orden de compra',
    'select fiscal position for sale order':
        'Posición fiscal a usar en la orden de venta',
    'Sales Team': 'Equipo de Ventas',
    'Priority': 'Prioridad',
    'Auto workflow': 'Flujo Automático',
    'Manage serial / lot number in Inter Company Transactions?':
        '¿Gestionar número de serie / lote en las transacciones inter-compañía?',
    'Auto validate Interwarehouse tansfer record?':
        '¿Validar automáticamente la transferencia inter-almacén?',

    # setu_intercompany_transaction - transferencia
    'Destination location': 'Ubicación de Destino',
    'IWT will be created for this location from the fulfiller warehouse.':
        'La transferencia inter-almacén (IWT) se va a crear hacia esta ubicación, '
        'desde el almacén abastecedor.',
    'Direct transfer to destination without transit location?':
        '¿Traslado directo al destino, sin ubicación de tránsito?',
    'Transfer Type': 'Tipo de Transferencia',
    'Inter Company': 'Inter-Compañía',
    'Inter Warehouse': 'Inter-Almacén',
    'In Progress': 'En Curso',
    'Origin ICT': 'ICT de Origen',
    'Origin Sale Order': 'Orden de Venta de Origen',
    'Locations': 'Ubicaciones',
    'Pickings': 'Transferencias',
    'Purchases': 'Compras',
    'Invoices': 'Facturas',
    'Total Invoice': 'Total de Facturas',
    'Total Pickings': 'Total de Transferencias',
    'Total Purchase': 'Total de Compras',
    'Total Sale': 'Total de Ventas',
    'Intercompany Transfer': 'Transferencia Inter-Compañía',
    'Intercompany Transfer Lines': 'Líneas de la Transferencia Inter-Compañía',
    'InterCompany Transfer Lines': 'Líneas de la Transferencia Inter-Compañía',
    'Inter Warehouse Transfer Lines': 'Líneas de la Transferencia Inter-Almacén',
    'Reverse Transfer Lines': 'Líneas de la Transferencia Inversa',
    'Intercompany Transaction': 'Transacción Inter-Compañía',
    'Inter Warehouse Transaction': 'Transacción Inter-Almacén',
    'Reverse Transaction': 'Transacción Inversa',
    'Reverse Transactions': 'Transacciones Inversas',
    'Setu Intercompany Transaction': 'Transacción Inter-Compañía',
    'Setu Inter Warehouse Transaction': 'Transacción Inter-Almacén',
    'Setu Reverse Transaction': 'Transacción Inversa',
    'Setu Intercompany Auto Workflow': 'Flujo Automático Inter-Compañía',
    'Intercompany Auto Workflow': 'Flujo Automático Inter-Compañía',
    'Invoice Auto Workflow': 'Flujo Automático de Facturación',
    'Sale / Purchase Auto Workflow': 'Flujo Automático de Venta / Compra',
    'Return': 'Devolución',
    'New': 'Nuevo',
    'Warning': 'Advertencia',

    # setu_intercompany_transaction - lineas
    'Category': 'Categoría',
    'Quantity': 'Cantidad',
    'Price': 'Precio',
    'Unit of Measure': 'Unidad de Medida',
    'Packaging': 'Empaque',
    'Packaging Quantity': 'Cantidad por Empaque',

    # setu_intercompany_transaction - flujo automatico
    'ICT Channels': 'Canales ICT',
    'ICT Auto Workflow': 'Flujo Automático ICT',
    'ICT Date': 'Fecha del ICT',
    'ICT User': 'Usuario ICT',
    'ICT Transfer Type': 'Tipo de Transferencia ICT',
    'ICT': 'ICT',
    'ICT User Guide': 'Manual del usuario ICT',
    'Open ICT User Guide': 'Abrir el manual del usuario ICT',
    'Create intercompany invoices?': '¿Crear facturas inter-compañía?',
    'Validate intercompany invoices?': '¿Validar las facturas inter-compañía?',
    'Validate intercompany record?': '¿Validar la transferencia inter-compañía?',
    'Validate intercompany sale / purchase?':
        '¿Validar la venta / compra inter-compañía?',

    # setu_intercompany_transaction - compania y orden de venta
    'Create Inter Company Transfer': 'Crear Transferencia Inter-Compañía',
    'Create Inter Warhouse Transfer': 'Crear Transferencia Inter-Almacén',
    'Distributed IWT?': '¿IWT distribuida?',
    'Stock Replenish source': 'Origen de la Reposición de Stock',
    'Do Nothing': 'No hacer nada',
    "Replenish stock from another company's warehouse":
        'Reponer stock desde el almacén de otra compañía',
    'Replenish stock from another warehouse of the same company':
        'Reponer stock desde otro almacén de la misma compañía',
    'Always replenish stock': 'Reponer stock siempre',
    'Always replenish stock (From other warehouses only)':
        'Reponer stock siempre (solo desde otros almacenes)',
    'Always replenish stock(Use Stock From Other Warehouses)':
        'Reponer stock siempre (usar stock de otros almacenes)',
    'As Per Company': 'Según la configuración de la compañía',
    'Manual - Select ICT Channel manually in sale order':
        'Manual - Elegir el canal ICT a mano en la orden de venta',
    'Manual - Select Inter Warehouse Channel manually in sale order':
        'Manual - Elegir el canal inter-almacén a mano en la orden de venta',
    'When all products out of stock in requestor company':
        'Cuando ningún producto tiene stock en la compañía solicitante',
    'When all products out of stock in requestor warehouse':
        'Cuando ningún producto tiene stock en el almacén solicitante',
    'When any single product is out of stock in requestor company':
        'Cuando algún producto no tiene stock en la compañía solicitante',
    'When any single product is out of stock in requestor warehouse':
        'Cuando algún producto no tiene stock en el almacén solicitante',
    'InterCompany Channels': 'Canales Inter-Compañía',
    'Intercompany Channel': 'Canal Inter-Compañía',
    'Interwarehouse Channel': 'Canal Inter-Almacén',
    'Interwarehouse Channels': 'Canales Inter-Almacén',
    'INTERCOMAPNY TRANSFER': 'TRANSFERENCIA INTER-COMPAÑÍA',
    'INTERWAREHOUSE TRANSFER': 'TRANSFERENCIA INTER-ALMACÉN',
    'Stock of': 'Stock de',
    'has been not found in any Companies!':
        'no se encontró en ninguna compañía.',
    'has been not found in any warehouses!':
        'no se encontró en ningún almacén.',
    'Inter company channel must be selected to create inter company record.':
        'Hay que elegir un canal inter-compañía para poder crear la transferencia.',
    'Inter company record has been already created.':
        'La transferencia inter-compañía ya fue creada.',
    'Inter warehouse record has been already created.':
        'La transferencia inter-almacén ya fue creada.',
    'Please add any product to do a transfer.':
        'Agregá al menos un producto para poder hacer la transferencia.',
    'Quantity should be greater than 0 to do a transfer.':
        'La cantidad tiene que ser mayor que 0 para poder hacer la transferencia.',

    # importacion de lineas
    'Import Intercompany Lines': 'Importar Líneas Inter-Compañía',
    'Import Lines': 'Importar Líneas',
    'CSV File': 'Archivo CSV',
    'The file must have an extention .csv':
        'El archivo tiene que tener extensión .csv',
    'The file must have an extension .csv':
        'El archivo tiene que tener extensión .csv',

    # setu_advance_reordering
    'Inter Company Transactions': 'Transacciones Inter-Compañía',
    'Inter Warehouse Transactions': 'Transacciones Inter-Almacén',
    'WH': 'Almacén',
    'FSN': 'Clasificación FSN',
    'IWT': 'IWT',
    'Vendor MOQ': 'Mínimo de Compra del Proveedor',
    'Columns name must be the same as described in the sample files':
        'Los nombres de las columnas tienen que ser los mismos que en los archivos de ejemplo',
    'It is the Vendor lead time will be in used in the planner.':
        'Es el plazo de entrega del proveedor que va a usar el planificador.',
    'Lead Days will be in Replenishment from Warehouses Configuration':
        'Los días de plazo se toman de la configuración de Reposición de Almacenes',
    'Demand generate based on past sales or forecasted sales':
        'La demanda se genera a partir de las ventas pasadas o del pronóstico de ventas',
    'Demand generate based on past sales or future sales':
        'La demanda se genera a partir de las ventas pasadas o de las ventas futuras',
    'Reorder amount will be calculated from the generated demands':
        'El importe a reordenar se calcula a partir de las demandas generadas',
    'Rounding Method will be set rounding according to selected value':
        'El método de redondeo define cómo se redondea según el valor elegido',
    'Sales possibility during the transit days or coverage days':
        'Venta posible durante los días de tránsito o de cobertura',
    'Set date and time advance reorder process occur':
        'Fecha y hora en que se ejecuta el proceso de reordenamiento',
    'Set days to maintain advance stock for products for next days':
        'Días de stock anticipado a mantener para los próximos días',
    'consider current period sales in the sales history calculation':
        'Incluir las ventas del período actual en el cálculo del histórico de ventas',
    'Default unit of measure used for all stock operations.':
        'Unidad de medida por defecto para todas las operaciones de stock.',
    'Reorder period is used to manage monthly timeframe for reordering':
        'El período de reordenamiento define la ventana mensual del reordenamiento',
    'Incorrect fiscal year end date: date must be greater than start date!':
        'Fecha de fin de ejercicio incorrecta: tiene que ser posterior a la de inicio.',
    'No sales forecast record found for this year to update Actual Sales.':
        'No hay pronóstico de ventas de este año para actualizar con las ventas reales.',
    'Quantities in Missing Forecasted sales lines should be greater then 0.':
        'Las cantidades de las líneas de pronóstico faltantes tienen que ser mayores que 0.',
    'Warehouse already added in configuration.Please select another one':
        'Ese almacén ya está en la configuración. Elegí otro.',

    # forum_reorder_origin
    'Has Unfulfillable': 'Tiene Reglas No Cumplibles',
    'Wizard': 'Asistente',

    # Etiquetas genericas. Estan traducidas para unos registros y para otros no, porque
    # ningun catalogo cubre los ir.model.fields de los modulos de Setu. Se incluyen para
    # que se apliquen a todas las referencias del bloque de una sola vez.
    'Active': 'Activo',
    'Created by': 'Creado por',
    'Created on': 'Creado el',
    'Display Name': 'Nombre a Mostrar',
    'Last Updated by': 'Última Actualización por',
    'Last Updated on': 'Última Actualización el',
    'Name': 'Nombre',
    'State': 'Estado',
    'Date': 'Fecha',
    'Product': 'Producto',
    'Sales': 'Ventas',
    'File Name': 'Nombre del Archivo',
}

TRADUCCIONES = dict(NUEVAS)
TRADUCCIONES.update(CORRECCIONES)
