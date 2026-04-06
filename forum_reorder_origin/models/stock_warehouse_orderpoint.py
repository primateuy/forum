# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare


class StockWarehouseOrderpoint(models.Model):
    _inherit = 'stock.warehouse.orderpoint'

    origin_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Almacén Origen',
        compute='_compute_origin_warehouse_id',
        store=True,
    )
    origin_qty_on_hand = fields.Float(
        string='[Origen] A la mano',
        compute='_compute_origin_quantities',
        digits='Product Unit of Measure',
    )
    origin_qty_available = fields.Float(
        string='[Origen] Disponible',
        compute='_compute_origin_quantities',
        digits='Product Unit of Measure',
    )
    origin_qty_forecast = fields.Float(
        string='[Origen] Pronosticado',
        compute='_compute_origin_quantities',
        digits='Product Unit of Measure',
    )
    origin_stock_warning = fields.Boolean(
        string='Alerta Stock Origen',
        compute='_compute_origin_stock_warning',
        search='_search_origin_stock_warning',
    )

    @api.model_create_multi
    def create(self, vals_list):
        product_ids = {vals['product_id'] for vals in vals_list if vals.get('product_id')}
        if product_ids:
            multiples = {
                p.id: p.product_tmpl_id.mutiplos_distribucion
                for p in self.env['product.product'].browse(product_ids)
            }
            for vals in vals_list:
                multiple = multiples.get(vals.get('product_id'), 0)
                if multiple and multiple > 1:
                    vals['qty_multiple'] = float(multiple)
        return super().create(vals_list)

    @api.depends('route_id', 'route_id.supplier_wh_id', 'warehouse_id', 'warehouse_id.resupply_wh_ids')
    def _compute_origin_warehouse_id(self):
        for op in self:
            origin_wh = False
            if op.route_id and op.route_id.supplier_wh_id:
                origin_wh = op.route_id.supplier_wh_id
            elif op.warehouse_id and op.warehouse_id.resupply_wh_ids:
                origin_wh = op.warehouse_id.resupply_wh_ids[0]
            op.origin_warehouse_id = origin_wh

    @api.depends('product_id', 'origin_warehouse_id')
    def _compute_origin_quantities(self):
        for op in self:
            if op.product_id and op.origin_warehouse_id:
                product = op.product_id.with_context(
                    warehouse=op.origin_warehouse_id.id,
                    location=op.origin_warehouse_id.lot_stock_id.id,
                )
                op.origin_qty_on_hand = product.qty_available
                op.origin_qty_available = product.free_qty
                op.origin_qty_forecast = product.virtual_available
            else:
                op.origin_qty_on_hand = 0.0
                op.origin_qty_available = 0.0
                op.origin_qty_forecast = 0.0

    @api.depends('origin_qty_available', 'qty_to_order')
    def _compute_origin_stock_warning(self):
        for op in self:
            if op.origin_warehouse_id and op.qty_to_order > 0:
                op.origin_stock_warning = float_compare(
                    op.origin_qty_available, op.qty_to_order,
                    precision_rounding=op.product_uom.rounding
                ) < 0
            else:
                op.origin_stock_warning = False

    def _search_origin_stock_warning(self, operator, value):
        """Permite filtrar por alerta de stock origen evaluando en tiempo real.

        Optimización: pre-filtra candidatos reales y agrupa por almacén origen
        para batch-compute free_qty (una query SQL por almacén, no por orderpoint).
        """
        from collections import defaultdict

        # Solo registros con almacén origen definido y cantidad a pedir
        candidate_ops = self.search([
            ('origin_warehouse_id', '!=', False),
            ('qty_to_order', '>', 0),
        ])

        warning_ids = set()
        if candidate_ops:
            # Agrupar por almacén origen → batch compute por almacén
            ops_by_wh = defaultdict(list)
            for op in candidate_ops:
                ops_by_wh[op.origin_warehouse_id.id].append(op)

            for wh_id, ops in ops_by_wh.items():
                wh = self.env['stock.warehouse'].browse(wh_id)
                product_ids = self.env['product.product'].browse(
                    list({op.product_id.id for op in ops})
                )
                # free_qty se batch-computa para todo el recordset en una sola query
                free_qty_map = {
                    p.id: p.free_qty
                    for p in product_ids.with_context(
                        warehouse=wh_id,
                        location=wh.lot_stock_id.id,
                    )
                }
                for op in ops:
                    free_qty = free_qty_map.get(op.product_id.id, 0.0)
                    if float_compare(
                        free_qty, op.qty_to_order,
                        precision_rounding=op.product_uom.rounding
                    ) < 0:
                        warning_ids.add(op.id)

        if operator == '=' and value:
            # True: solo los que tienen warning
            return [('id', 'in', list(warning_ids))]
        else:
            # False: candidatos sin warning + los que no tienen almacén origen / qty=0
            non_warning_candidate_ids = [op.id for op in candidate_ops if op.id not in warning_ids]
            non_candidate_ops = self.search([
                '|',
                ('origin_warehouse_id', '=', False),
                ('qty_to_order', '<=', 0),
            ])
            return [('id', 'in', non_warning_candidate_ids + non_candidate_ops.ids)]

    def action_replenish(self, force_to_max=False):
        """Override para validar stock en origen antes de reabastecer."""
        unfulfillable = self._check_origin_stock()
        if unfulfillable:
            self._raise_origin_stock_error(unfulfillable)
        return super().action_replenish(force_to_max=force_to_max)

    def action_replenish_auto(self):
        """Override para validar stock en origen antes de automatizar."""
        unfulfillable = self._check_origin_stock()
        if unfulfillable:
            self._raise_origin_stock_error(unfulfillable)
        return super().action_replenish_auto()

    def action_open_origin_warning_wizard(self):
        """Abre wizard de confirmación para forzar reabastecimiento con stock insuficiente."""
        unfulfillable = self._check_origin_stock()
        message = self._build_warning_message(unfulfillable) if unfulfillable else _(
            "No hay reglas con stock insuficiente en origen en la selección actual."
        )
        wizard = self.env['forum.reorder.warning.wizard'].create({
            'message': message,
            'orderpoint_ids': [(6, 0, self.ids)],
            'has_unfulfillable': bool(unfulfillable),
        })
        return {
            'name': _('Alerta de Stock en Origen'),
            'type': 'ir.actions.act_window',
            'res_model': 'forum.reorder.warning.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
            'views': [(False, 'form')],
        }

    def _check_origin_stock(self):
        """Retorna lista de orderpoints donde el stock de origen es insuficiente."""
        unfulfillable = []
        for op in self:
            if not op.origin_warehouse_id or op.qty_to_order <= 0:
                continue
            if float_compare(
                op.origin_qty_available, op.qty_to_order,
                precision_rounding=op.product_uom.rounding
            ) < 0:
                unfulfillable.append({
                    'orderpoint_id': op.id,
                    'product': op.product_id.display_name,
                    'location': op.location_id.display_name,
                    'origin_warehouse': op.origin_warehouse_id.display_name,
                    'available': op.origin_qty_available,
                    'requested': op.qty_to_order,
                })
        return unfulfillable

    def _build_warning_message(self, unfulfillable):
        detail_lines = []
        for item in unfulfillable:
            detail_lines.append(
                f"• {item['product']} en {item['location']}: "
                f"disponible en {item['origin_warehouse']} = {item['available']}, "
                f"solicitado = {item['requested']}"
            )
        return _(
            "Stock insuficiente en origen para las siguientes reglas:\n\n%s"
        ) % '\n'.join(detail_lines)

    def _raise_origin_stock_error(self, unfulfillable):
        message = self._build_warning_message(unfulfillable)
        raise UserError(message)
