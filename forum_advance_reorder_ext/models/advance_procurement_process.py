# -*- coding: utf-8 -*-
import logging

from dateutil import relativedelta

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AdvanceProcurementProcess(models.Model):
    _inherit = 'advance.procurement.process'

    warehouse_group_ids = fields.Many2many(
        'stock.warehouse.group',
        'forum_procurement_process_wh_group_rel',
        'procurement_process_id',
        'warehouse_group_id',
        string='Grupos de Almacenes',
        help='Al presionar "Agregar almacenes de los grupos" se crea una línea de '
             'configuración por cada almacén de estos grupos que todavía no esté cargado.',
    )

    def action_add_warehouses_from_groups(self):
        """Expande los grupos elegidos en líneas de config_ids, una por almacén destino.

        Consideraciones:
        - Se saltea el almacén origen del proceso: onchange_procurement_warehouse_id ya lo
          carga como primera línea, y action_procurement_internal_transfer lo excluye de las
          transferencias. Duplicarlo dispararía el @api.constrains('config_ids') de Setu.
        - Se saltean los almacenes ya presentes, por el mismo constraint.
        - Las fechas se siembran con el mismo criterio que onchange_procurement_warehouse_id
          y después se ejecutan los onchange de la línea, igual que hace
          create_warehouse_replenishment, para que resuelva el canal ICT/IWT y los plazos.
        """
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Solo se pueden agregar almacenes mientras el proceso está en borrador.'))
        if not self.warehouse_group_ids:
            raise UserError(_('Elegí al menos un grupo de almacenes.'))
        if not self.warehouse_id:
            raise UserError(_('Definí primero el almacén de origen del proceso.'))

        almacenes_grupo = self.warehouse_group_ids.mapped('warehouse_ids')
        ya_cargados = self.config_ids.mapped('warehouse_id')
        pendientes = almacenes_grupo - ya_cargados - self.warehouse_id

        if not pendientes:
            return self._forum_notificacion(
                _('No se agregaron almacenes'),
                _('Los almacenes de los grupos elegidos ya están cargados en la configuración.'),
                'warning',
            )

        procurement_date = self.procurement_date.date()
        advance_stock_date = procurement_date + relativedelta.relativedelta(days=1)

        self.config_ids = [
            (0, 0, {
                'warehouse_id': almacen.id,
                'shipment_date': procurement_date,
                'shipment_arrival_date': procurement_date,
                'advance_stock_start_date': advance_stock_date,
                'advance_stock_end_date': advance_stock_date,
            })
            for almacen in pendientes
        ]

        # Resolver canal y plazos de las líneas recién creadas.
        nuevas = self.config_ids.filtered(lambda c: c.warehouse_id in pendientes)
        for config in nuevas:
            config.onchange_warehouse_id()
            config.onchange_transit_days()
            config.onchange_shipment_arrival_date()

        sin_canal = nuevas.filtered(
            lambda c: not c.inter_company_channel_id and not c.inter_warehouse_channel_id
        )
        if sin_canal:
            return self._forum_notificacion(
                _('Almacenes agregados con advertencia'),
                _('Se agregaron %s almacenes. %s quedaron sin canal ICT/IWT resuelto: %s') % (
                    len(pendientes),
                    len(sin_canal),
                    ', '.join(sin_canal.mapped('warehouse_id.display_name')),
                ),
                'warning',
            )

        return self._forum_notificacion(
            _('Almacenes agregados'),
            _('Se agregaron %s almacenes desde %s grupos.') % (
                len(pendientes), len(self.warehouse_group_ids)),
            'success',
        )

    def _forum_notificacion(self, titulo, mensaje, tipo):
        """Devuelve una notificación para dar feedback en la misma vista."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': titulo,
                'message': mensaje,
                'type': tipo,
                'sticky': False,
            },
        }
