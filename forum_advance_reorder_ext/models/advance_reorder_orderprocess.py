# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class AdvanceReorderOrderProcess(models.Model):
    _inherit = 'advance.reorder.orderprocess'

    product_category_ids = fields.Many2many(
        'product.category',
        'forum_reorder_orderprocess_categ_rel',
        'orderprocess_id',
        'categ_id',
        string='Categorías de Producto',
        help='Al presionar "Agregar productos de las categorías" se cargan en Productos '
             'todos los productos de estas categorías y de sus categorías hijas.',
    )

    def action_add_products_from_categories(self):
        """Carga en product_ids los productos de las categorías elegidas y de sus hijas.

        Se intersecta con computed_product_ids porque ese campo ya encierra los filtros que
        aplica el propio Setu (purchase_ok, compañía y, si hay proveedor elegido, que el
        producto tenga tarifa de ese proveedor). Es además el dominio de la vista, así que
        garantiza que no se agreguen productos que la vista rechazaría.
        """
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Solo se pueden agregar productos mientras el proceso está en borrador.'))
        if not self.product_category_ids:
            raise UserError(_('Elegí al menos una categoría de producto.'))

        candidatos = self.env['product.product'].forum_products_from_categories(
            self.product_category_ids
        )
        permitidos = candidatos & self.sudo().computed_product_ids
        nuevos = permitidos - self.product_ids

        if not nuevos:
            return self._forum_notificacion(
                _('No se agregaron productos'),
                _('Las categorías elegidas no aportan productos nuevos habilitados para este proceso.'),
                'warning',
            )

        self.product_ids = [(4, product.id) for product in nuevos]
        return self._forum_notificacion(
            _('Productos agregados'),
            _('Se agregaron %s productos desde %s categorías.') % (len(nuevos), len(self.product_category_ids)),
            'success',
        )

    def _forum_notificacion(self, titulo, mensaje, tipo):
        """Devuelve una notificación sticky-less para dar feedback en la misma vista."""
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

    def prepare_reorder_line_vals(self, config, sales_data, generate_demand_with):
        """Redondea la demanda calculada al múltiplo de distribución del producto.

        Setu escribe directamente sobre las líneas que ya existen (line_id.write) y solo
        devuelve tuplas (0, 0, {...}) para las nuevas, así que hay que corregir los dos
        caminos: las tuplas devueltas y las líneas ya persistidas por el super().
        """
        vals = super().prepare_reorder_line_vals(config, sales_data, generate_demand_with)

        product_obj = self.env['product.product']

        # 1) Líneas nuevas: todavía son diccionarios, se corrigen antes de crearse.
        for command in vals:
            if command[0] != 0 or not command[2]:
                continue
            line_vals = command[2]
            demanda = line_vals.get('demand_adjustment_qty') or 0.0
            if demanda <= 0 or not line_vals.get('product_id'):
                continue
            product = product_obj.browse(line_vals['product_id'])
            line_vals['demand_adjustment_qty'] = product.forum_round_to_distribution_multiple(demanda)

        # 2) Líneas que el super() ya escribió en base.
        lineas_existentes = self.line_ids.filtered(
            lambda l: l.warehouse_group_id == config.warehouse_group_id and l.demand_adjustment_qty > 0
        )
        for linea in lineas_existentes:
            redondeada = linea.product_id.forum_round_to_distribution_multiple(linea.demand_adjustment_qty)
            if float_compare(redondeada, linea.demand_adjustment_qty,
                             precision_rounding=linea.product_id.uom_id.rounding or 0.01) != 0:
                linea.demand_adjustment_qty = redondeada

        return vals

    def _prepare_purchase_order_line_vals(self, fpos, warehouse_group_id):
        """Redondea la cantidad de la línea de orden de compra al múltiplo del producto."""
        po_line_vals = super()._prepare_purchase_order_line_vals(fpos, warehouse_group_id)

        product_obj = self.env['product.product']
        for command in po_line_vals:
            if command[0] != 0 or not command[2]:
                continue
            line_vals = command[2]
            cantidad = line_vals.get('product_qty') or 0.0
            if cantidad <= 0 or not line_vals.get('product_id'):
                continue
            product = product_obj.browse(line_vals['product_id'])
            line_vals['product_qty'] = product.forum_round_to_distribution_multiple(cantidad)

        return po_line_vals
