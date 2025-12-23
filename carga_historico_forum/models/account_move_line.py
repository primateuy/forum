# -*- coding: utf-8 -*-

from odoo import models, fields, api


class AccountMoveLine(models.Model):
    """
    Extensión del modelo account.move.line para agregar campos de migración.
    
    Este modelo agrega campos adicionales a las líneas de factura que permiten:
    - Identificar productos cuando no existen en Odoo
    - Guardar snapshots de datos de Odoo al momento de emisión
    - Almacenar costos para reportes Forum
    
    Los campos snapshot NO se recalculan automáticamente y representan
    la verdad histórica al momento de emisión/importación.
    """
    _inherit = "account.move.line"

    # ========== Campos de identificación de producto (cuando no existe en Odoo) ==========
    
    # SKU original del producto en el sistema origen
    # Clave importante si se usa producto genérico en Odoo
    x_mig_product_sku = fields.Char(
        string='SKU original',
        help='SKU del producto en el sistema origen. Útil para búsqueda y mapeo cuando se usa producto genérico.',
    )

    # Nombre del producto en el sistema origen
    # Para auditoría y legibilidad cuando el producto es genérico
    x_mig_product_name = fields.Char(
        string='Producto (texto origen)',
        help='Nombre del producto en el sistema origen. Para auditoría y legibilidad cuando el producto es genérico.',
    )

    # ========== Campos snapshot de datos propios de Odoo al momento de emisión ==========
    
    # Snapshot de las etiquetas del producto en Odoo
    # Copia de los tags que tenía el producto al emitir/importar
    # Se usa texto porque los tags suelen cambiar mucho y no siempre se quiere mantener integridad histórica
    x_mig_product_tags_snapshot = fields.Text(
        string='Etiquetas de producto (snapshot)',
        help='Copia de los tags que tenía el producto en Odoo al momento de emitir/importar la factura. '
             'Este valor no se recalcula automáticamente y representa la verdad histórica.',
    )

    # Agrupador de precios en formato Many2one (recomendado)
    # Congela el agrupador de precios usado en ese momento mediante referencia al modelo
    # Nota: Si necesitas usar un modelo diferente, cambia 'product.pricelist' por el modelo correspondiente
    x_mig_price_group_snapshot_id = fields.Many2one(
        'product.pricelist',
        string='Agrupador de precios (snapshot)',
        help='Agrupador de precios usado al momento de emitir/importar la factura. '
             'Valor congelado que no se recalcula automáticamente y representa la verdad histórica.',
        ondelete='set null',
    )

    # Agrupador de precios en formato texto (alternativa al Many2one)
    # Congela el agrupador de precios usado en ese momento
    x_mig_price_group_snapshot = fields.Char(
        string='Agrupador de precios (texto)',
        help='Agrupador de precios usado al momento de emitir/importar la factura. '
             'Valor congelado que no se recalcula automáticamente. '
             'Alternativa al campo Many2one si no se quiere depender del modelo.',
    )

    # ========== Campos de costos para reportes Forum ==========
    
    # Costo operativo según criterio Forum
    # Usado para reportes específicos
    x_mig_operational_cost = fields.Monetary(
        string='Costo operativo',
        currency_field='currency_id',
        help='Costo operativo según criterio Forum usado para reportes. '
             'Puede ser establecido por el importador o lógica futura.',
    )

    # Snapshot del costo estándar del producto
    # Costo estándar congelado al momento de emisión
    x_mig_standard_cost_snapshot = fields.Monetary(
        string='Costo estándar (snapshot)',
        currency_field='currency_id',
        help='Costo estándar del producto congelado al momento de emitir/importar la factura. '
             'Este valor no se recalcula automáticamente y representa la verdad histórica.',
    )

