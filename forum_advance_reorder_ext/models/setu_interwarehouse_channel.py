# -*- coding: utf-8 -*-
from odoo import fields, models


class SetuInterwarehouseChannel(models.Model):
    _inherit = 'setu.interwarehouse.channel'

    picking_type_id = fields.Many2one(
        'stock.picking.type',
        string='Tipo de Operación',
        ondelete='restrict',
        domain="[('code', '=', 'internal'), ('warehouse_id', '=', fulfiller_warehouse_id)]",
        help='Tipo de operación para el traslado generado desde el almacén origen. '
             'En el traslado en dos pasos se usa para el primer picking (origen → tránsito). '
             'Si se deja vacío se mantiene el comportamiento por defecto de Setu '
             '(tipo de traslado interno del almacén).',
    )
    requestor_picking_type_id = fields.Many2one(
        'stock.picking.type',
        string='Tipo de Operación (2° paso)',
        ondelete='restrict',
        domain="[('code', '=', 'internal'), ('warehouse_id', '=', requestor_warehouse_id)]",
        help='Tipo de operación del segundo picking (tránsito → destino) en el traslado en '
             'dos pasos. No se usa cuando el canal está configurado como traslado directo.',
    )
    picking_type_wms_integration = fields.Boolean(
        string='Origen viaja al WMS',
        related='picking_type_id.integracion_wms',
        readonly=True,
    )
    requestor_picking_type_wms_integration = fields.Boolean(
        string='Destino viaja al WMS',
        related='requestor_picking_type_id.integracion_wms',
        readonly=True,
    )
