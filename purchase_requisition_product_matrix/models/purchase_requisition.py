# -*- coding: utf-8 -*-
import json

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PurchaseRequisition(models.Model):
    _inherit = 'purchase.requisition'

    amount_untaxed = fields.Monetary(
        string='Untaxed Amount',
        compute='_compute_amount_untaxed',
        currency_field='currency_id',
        store=True,
        readonly=True,
    )
    grid_product_tmpl_id = fields.Many2one(
        'product.template',
        store=False,
        help="Technical field used to open the product matrix.",
    )
    grid_update = fields.Boolean(
        default=False,
        store=False,
        help="Indicates whether the matrix payload should be applied on the agreement lines.",
    )
    grid = fields.Char(
        store=False,
        help="Technical storage used to open and apply the product matrix.",
    )

    @api.depends('line_ids.price_subtotal')
    def _compute_amount_untaxed(self):
        for requisition in self:
            requisition.amount_untaxed = sum(requisition.line_ids.mapped('price_subtotal'))

    @api.onchange('grid_product_tmpl_id')
    def _set_grid_up(self):
        if self.grid_product_tmpl_id:
            self.grid_update = False
            self.grid = json.dumps(self._get_matrix(self.grid_product_tmpl_id))

    @api.onchange('grid')
    def _apply_grid(self):
        if not (self.grid and self.grid_update):
            return

        grid = json.loads(self.grid)
        product_template = self.env['product.template'].browse(grid['product_template_id'])
        dirty_cells = grid['changes']
        attribute_value_model = self.env['product.template.attribute.value']
        line_model = self.env['purchase.requisition.line']
        default_line_vals = {}
        new_lines = []
        product_ids = set()

        for cell in dirty_cells:
            combination = attribute_value_model.browse(cell['ptav_ids'])
            no_variant_attribute_values = combination - combination._without_no_variant_attributes()
            product = product_template._create_product_variant(combination)
            requisition_lines = self.line_ids.filtered(
                lambda line: (line._origin or line).product_id == product
                and (line._origin or line).product_no_variant_attribute_value_ids == no_variant_attribute_values
            )

            old_qty = sum(requisition_lines.mapped('product_qty'))
            qty = cell['qty']
            diff = qty - old_qty
            if not diff:
                continue

            product_ids.add(product.id)

            if requisition_lines:
                if qty == 0:
                    self.line_ids -= requisition_lines
                else:
                    if len(requisition_lines) > 1:
                        raise ValidationError(
                            _("No se puede cambiar la cantidad de un producto presente en multiples lineas del acuerdo.")
                        )
                    requisition_lines.product_qty = qty
            else:
                if not default_line_vals:
                    default_line_vals = line_model.default_get(line_model._fields.keys())
                # Descripción de variante en formato nativo: PULOVER (ROJO, XL)
                variant_name = product.product_template_attribute_value_ids._get_combination_name()
                product_name = product_template.name
                variant_description = "%s (%s)" % (product_name, variant_name) if variant_name else product_name
                new_lines.append((0, 0, dict(
                    default_line_vals,
                    product_id=product.id,
                    product_qty=qty,
                    product_uom_id=product.uom_po_id.id,
                    product_description_variants=variant_description,
                    product_no_variant_attribute_value_ids=[(6, 0, no_variant_attribute_values.ids)],
                    schedule_date=self.schedule_date,
                )))

        if new_lines:
            self.update({'line_ids': new_lines})

        # Recalcular UoM y precio para líneas nuevas (el onchange establece uom_po_id y price_unit)
        if product_ids:
            for line in self.line_ids.filtered(lambda l: l.product_id.id in product_ids):
                saved_qty = line.product_qty
                line._onchange_product_id()
                # Restaurar la cantidad real ya que _onchange_product_id la pone en 1.0
                line.product_qty = saved_qty

    def _get_matrix(self, product_template):
        def has_ptavs(line, sorted_attr_ids):
            ptav = line.product_template_attribute_value_ids.ids
            pnav = line.product_no_variant_attribute_value_ids.ids
            pav = pnav + ptav
            pav.sort()
            return pav == sorted_attr_ids

        matrix = product_template._get_template_matrix(
            company_id=self.company_id,
            currency_id=self.currency_id,
        )
        if self.line_ids:
            lines = matrix['matrix']
            requisition_lines = self.line_ids.filtered(lambda line: line.product_template_id == product_template)
            for row in lines:
                for cell in row:
                    if not cell.get('name', False):
                        requisition_line = requisition_lines.filtered(lambda line: has_ptavs(line, cell['ptav_ids']))
                        if requisition_line:
                            cell.update({
                                'qty': sum(requisition_line.mapped('product_qty')),
                            })

        matrix['product_template_id'] = product_template.id
        return matrix


class PurchaseRequisitionLine(models.Model):
    _inherit = 'purchase.requisition.line'

    currency_id = fields.Many2one(
        related='requisition_id.currency_id',
        store=True,
        readonly=True,
        string='Currency',
    )
    product_template_id = fields.Many2one(
        'product.template',
        string='Product',
        related='product_id.product_tmpl_id',
        domain=[('purchase_ok', '=', True)],
    )
    is_configurable_product = fields.Boolean(
        string='Is the product configurable?',
        related='product_template_id.has_configurable_attributes',
    )
    product_template_attribute_value_ids = fields.Many2many(
        related='product_id.product_template_attribute_value_ids',
        readonly=True,
    )
    product_no_variant_attribute_value_ids = fields.Many2many(
        'product.template.attribute.value',
        string='Product attribute values that do not create variants',
        ondelete='restrict',
    )
    price_subtotal = fields.Monetary(
        string='Subtotal',
        compute='_compute_price_subtotal',
        currency_field='currency_id',
        store=True,
    )

    @api.depends('product_qty', 'price_unit')
    def _compute_price_subtotal(self):
        for line in self:
            line.price_subtotal = line.product_qty * line.price_unit

    @api.depends(
        'requisition_id.purchase_ids.state',
        'requisition_id.purchase_ids.order_line.product_id',
        'requisition_id.purchase_ids.order_line.product_no_variant_attribute_value_ids',
        'requisition_id.purchase_ids.order_line.product_qty',
        'product_no_variant_attribute_value_ids',
    )
    def _compute_ordered_qty(self):
        line_found = {}
        for line in self:
            total = 0.0
            line_key = (
                line.requisition_id.id,
                line.product_id.id,
                tuple(sorted(line.product_no_variant_attribute_value_ids.ids)),
            )
            for po in line.requisition_id.purchase_ids.filtered(lambda purchase_order: purchase_order.state in ['purchase', 'done']):
                po_lines = po.order_line.filtered(
                    lambda order_line: order_line.product_id == line.product_id
                    and order_line.product_no_variant_attribute_value_ids == line.product_no_variant_attribute_value_ids
                )
                for po_line in po_lines:
                    if po_line.product_uom != line.product_uom_id:
                        total += po_line.product_uom._compute_quantity(po_line.product_qty, line.product_uom_id)
                    else:
                        total += po_line.product_qty
            if line_key not in line_found:
                line.qty_ordered = total
                line_found[line_key] = True
            else:
                line.qty_ordered = 0

    @api.onchange('product_id')
    def _onchange_product_id(self):
        super()._onchange_product_id()
        if not self.product_id or not self.requisition_id.vendor_id or self.price_unit:
            return
        seller = self.product_id._select_seller(
            partner_id=self.requisition_id.vendor_id,
            quantity=self.product_qty,
            date=fields.Date.today(),
            uom_id=self.product_uom_id,
        )
        if seller:
            self.price_unit = seller.price

    def _get_variant_extra_description(self):
        self.ensure_one()
        if not self.product_no_variant_attribute_value_ids:
            return False
        return '\n'.join(
            f"{value.attribute_id.name}: {value.name}"
            for value in self.product_no_variant_attribute_value_ids
        )

    def _prepare_purchase_order_line(self, name, product_qty=0.0, price_unit=0.0, taxes_ids=False):
        vals = super()._prepare_purchase_order_line(
            name=name,
            product_qty=product_qty,
            price_unit=price_unit,
            taxes_ids=taxes_ids,
        )
        extra_description = self._get_variant_extra_description()
        if extra_description and extra_description not in vals['name']:
            vals['name'] = f"{vals['name']}\n{extra_description}"
        vals['product_no_variant_attribute_value_ids'] = [
            (6, 0, self.product_no_variant_attribute_value_ids.ids),
        ]
        return vals
