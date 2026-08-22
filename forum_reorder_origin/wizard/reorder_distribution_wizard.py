# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.primate_reposicion_avanzada.models.distribution_strategy_mixin import (
    DISTRIBUTION_STRATEGIES,
)

_logger = logging.getLogger(__name__)


class ForumReorderDistributionWizard(models.TransientModel):
    _name = 'forum.reorder.distribution.wizard'
    _inherit = ['primate.distribution.strategy.mixin']
    _description = 'Distribuir stock insuficiente entre reglas del mismo origen'

    distribution_strategy = fields.Selection(
        selection=DISTRIBUTION_STRATEGIES,
        string='Estrategia de Distribución',
        required=True,
        default='proporcional',
        help='Cómo repartir el stock disponible del almacén origen entre las reglas que '
             'compiten por él.',
    )
    strategy_warehouse_ids = fields.Many2many(
        'stock.warehouse',
        'forum_reorder_distribution_wizard_wh_rel',
        'wizard_id',
        'warehouse_id',
        string='Prioridad de Almacenes',
        help='Solo para la estrategia por prioridad. El orden efectivo es el del campo '
             '"Secuencia" de cada almacén; los que no figuren se atienden al final.',
    )
    group_ids = fields.One2many(
        'forum.reorder.distribution.wizard.group',
        'wizard_id',
        string='Grupos con faltante',
        readonly=True,
    )
    orderpoint_ids = fields.Many2many(
        'stock.warehouse.orderpoint',
        'forum_reorder_distribution_wizard_op_rel',
        'wizard_id',
        'orderpoint_id',
        string='Reglas alcanzadas',
    )

    @api.model
    def default_get(self, fields_list):
        """Arma los grupos con faltante a partir de las reglas seleccionadas.

        Si no hay selección puntual, se toman todas las reglas candidatas: es el caso de
        usarlo sobre el filtro "Reglas NO cumplibles" sin tildar filas.
        """
        res = super().default_get(fields_list)
        op_obj = self.env['stock.warehouse.orderpoint']
        ids_activos = self.env.context.get('active_ids') or []
        seleccionadas = op_obj.browse(ids_activos) if ids_activos else op_obj

        grupos = op_obj._group_candidates_by_origin()
        lineas_grupo, alcanzadas = [], op_obj
        for (product_id, warehouse_id), datos in grupos.items():
            if not datos['shortfall']:
                continue  # el grupo entra en el stock: nada que repartir
            del_grupo = datos['orderpoints']
            if seleccionadas and not (del_grupo & seleccionadas):
                continue  # el usuario no eligió ninguna regla de este grupo
            alcanzadas |= del_grupo
            lineas_grupo.append((0, 0, {
                'product_id': product_id,
                'origin_warehouse_id': warehouse_id,
                'demand_qty': datos['demand'],
                'available_qty': datos['available'],
                'shortfall_qty': datos['shortfall'],
                'orderpoint_count': len(del_grupo),
            }))

        if not lineas_grupo:
            raise UserError(_(
                'No hay grupos con faltante en la selección. Todas las reglas alcanzadas '
                'entran en el stock disponible de su almacén origen.'))

        res.update({'group_ids': lineas_grupo, 'orderpoint_ids': [(6, 0, alcanzadas.ids)]})
        return res

    def action_apply(self):
        """Reparte el stock de cada grupo y escribe el resultado en qty_to_order.

        No genera ninguna orden ni ejecuta reabastecimiento: deja las cantidades listas para
        que el usuario use el botón estándar "Ordenar". Y no agrega ninguna validación sobre
        el valor escrito — una vez distribuido, qty_to_order vuelve a comportarse como el
        campo estándar de Odoo, de libre edición.
        """
        self.ensure_one()
        op_obj = self.env['stock.warehouse.orderpoint']
        grupos = op_obj._group_candidates_by_origin()
        prioridad_wh = self.strategy_warehouse_ids.ids
        total_reglas, detalle = 0, []

        for linea in self.group_ids:
            clave = (linea.product_id.id, linea.origin_warehouse_id.id)
            datos = grupos.get(clave)
            if not datos or not datos['shortfall']:
                continue

            del_grupo = datos['orderpoints']
            multiple = max(del_grupo.mapped('qty_multiple') or [1]) or 1
            candidatos = [
                {
                    'key': op.id,
                    'demand_qty': op.qty_to_order,
                    'ads': self._ads_del_almacen(op),
                    'sequence': op.warehouse_id.id,
                }
                for op in del_grupo
            ]
            prioridad = [
                op.id
                for wh_id in prioridad_wh
                for op in del_grupo.filtered(lambda o: o.warehouse_id.id == wh_id)
            ]
            # El paso de reparto sale del redondeo de la unidad de medida: para "Units"
            # es 1, así que el reparto queda en unidades enteras. Sin pasarlo, el mixin
            # usa su default de 0,01 y escribe cantidades como 0,28 en productos que se
            # manejan por unidad.
            paso = del_grupo[0].product_uom.rounding or 1.0
            asignado = self.compute_partial_distribution(
                self.distribution_strategy,
                candidatos,
                datos['available'],
                multiple,
                priority_ids=prioridad,
                precision_rounding=paso,
            )
            for op in del_grupo:
                op.qty_to_order = asignado.get(op.id, 0.0)
            total_reglas += len(del_grupo)
            detalle.append('%s / %s: %s reglas, %s repartidas sobre %s pedidas' % (
                linea.product_id.display_name, linea.origin_warehouse_id.display_name,
                len(del_grupo), datos['available'], datos['demand']))

        _logger.info("Distribución de stock insuficiente aplicada (%s): %s",
                     self.distribution_strategy, '; '.join(detalle))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Distribución aplicada'),
                'message': _('Se recalculó "Por Ordenar" en %(reglas)s reglas de '
                             '%(grupos)s grupo(s). Las cantidades quedan editables a mano.',
                             reglas=total_reglas, grupos=len(self.group_ids)),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _ads_del_almacen(self, orderpoint):
        """Venta diaria promedio de la regla, para la estrategia por rotación.

        Se toma del propio orderpoint: setu_advance_reordering ya mantiene ads_qty ahí. Si el
        campo no existe o está en cero, el mixin cae al orden de prioridad.
        """
        return float(getattr(orderpoint, 'ads_qty', 0.0) or 0.0)


class ForumReorderDistributionWizardGroup(models.TransientModel):
    _name = 'forum.reorder.distribution.wizard.group'
    _description = 'Grupo producto / almacén origen con faltante de stock'

    wizard_id = fields.Many2one(
        'forum.reorder.distribution.wizard', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Producto', readonly=True)
    origin_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Almacén Origen', readonly=True)
    orderpoint_count = fields.Integer('Reglas', readonly=True)
    demand_qty = fields.Float('Demanda del grupo', readonly=True,
                              digits='Product Unit of Measure')
    available_qty = fields.Float('Disponible en origen', readonly=True,
                                 digits='Product Unit of Measure')
    shortfall_qty = fields.Float('Faltante', readonly=True,
                                 digits='Product Unit of Measure')
