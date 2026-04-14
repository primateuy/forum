from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    autofacturar_por_limite = fields.Boolean(
        string="Autofacturar por límite de líneas",
        default=False,
        help="Si está activo, al crear una orden de venta desde el POS se verificará si "
             "el acumulado de líneas por facturar supera el límite del punto de emisión. "
             "En ese caso se generará automáticamente una factura en borrador.",
    )
