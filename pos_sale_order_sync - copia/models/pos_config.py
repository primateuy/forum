from odoo import api, fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    crear_order_venta = fields.Boolean('Crear orden de venta', default=False)
    tipo_pedido_venta_id = fields.Many2one('sale.order.type', 'Tipo de Pedido de Venta')
