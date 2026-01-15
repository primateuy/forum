# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    crossdocking_location_id = fields.Many2one(
        'stock.location',
        string='Ubicación Crossdocking',
        help='Ubicación de tránsito para operaciones de crossdocking en este almacén. Se crea automáticamente como hija de "Transferencia de Almacenes"'
    )
    crossdocking_type_id = fields.Many2one(
        'stock.picking.type',
        string='Tipo de Operación Crossdocking',
        help='Tipo de operación para crossdocking (transferencia interna) en este almacén. La ubicación de destino se asigna dinámicamente.'
    )
    crossdocking_reception_type_id = fields.Many2one(
        'stock.picking.type',
        string='Tipo de Operación Recepción Crossdocking',
        help='Tipo de operación para la recepción de mercadería en crossdocking en este almacén'
    )

    @api.model
    def create(self, vals):
        warehouse = super(StockWarehouse, self).create(vals)
        warehouse._create_crossdocking_location()
        return warehouse

    def _create_crossdocking_location(self):
        """Crea la ubicación de crossdocking para el almacén"""
        for warehouse in self:
            if not warehouse.crossdocking_location_id:
                # Buscar o crear la ubicación padre de transferencias
                transfer_location = self.env['stock.location'].search([
                    ('usage', '=', 'transit'),
                    ('company_id', '=', warehouse.company_id.id),
                    ('name', '=', 'Transferencia de Almacenes')
                ], limit=1)

                if not transfer_location:
                    transfer_location = self.env['stock.location'].create({
                        'name': 'Transferencia de Almacenes',
                        'usage': 'transit',
                        'company_id': warehouse.company_id.id,
                    })

                # Crear ubicación de crossdocking
                crossdocking_location = self.env['stock.location'].create({
                    'name': f'{warehouse.name}/Transferir x Crossdocking',
                    'usage': 'transit',
                    'location_id': transfer_location.id,
                    'company_id': warehouse.company_id.id,
                })

                warehouse.crossdocking_location_id = crossdocking_location.id


    