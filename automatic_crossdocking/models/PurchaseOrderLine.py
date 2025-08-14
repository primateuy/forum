from odoo import api, models, fields

import logging

_logger = logging.getLogger(__name__);


        

class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    use_crossdock = fields.Boolean(
        string="Usar Cross-Docking",
        help="Si está activo, la línea se enviará directamente al punto de venta."
    )
    
    line_crossdock_percentage = fields.Float(
        string="% Cross-Docking (Línea)",
        help="Porcentaje de la cantidad que irá a cross-docking.",
        groups="automatic_crossdocking.group_crossdock_editors"
    )
    
    distribution_multiple = fields.Integer(
        string="Múltiplo de Distribución",
        default=1,
        help="Ej: Si es 6, la cantidad se redondea a múltiplos de 6 (cajas)."
    )