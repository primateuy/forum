from odoo import fields, models, api, _


class AdvanceReorderOrderProcessSummary(models.Model):
    _name = 'advance.reorder.orderprocess.summary'
    _description = "Advance Reorder with Demand Generation Lines"

    @api.depends('vendor_moq', 'demanded_qty')
    def _compute_is_order_moq(self):
        for record in self:
            is_order_moq = False
            if record.vendor_moq > record.demanded_qty:
                is_order_moq = True
            record.is_order_moq = is_order_moq

    def _default_weight_uom_name(self):
        weight_uom = self.env['product.template']._get_weight_uom_id_from_ir_config_parameter()
        return weight_uom and weight_uom.name or ''

    product_id = fields.Many2one('product.product', string="Product")
    vendor_moq = fields.Integer("Vendor MOQ")
    demanded_qty = fields.Integer("Demand")
    is_order_moq = fields.Boolean("Is Order MOQ ?", compute='_compute_is_order_moq', store=True)
    reorder_process_id = fields.Many2one('advance.reorder.orderprocess', string="Advance reorder process")
    product_volume = fields.Float('Volume', related='product_id.volume')
    volume_uom_name = fields.Char('Volume UOM', related='product_id.volume_uom_name')
    product_weight = fields.Float('Weight', related='product_id.weight')
    weight_uom_name = fields.Char('Weight UOM', default=_default_weight_uom_name)
    order_qty = fields.Integer("To be ordered", help='Quantity to be ordered')
    total_volume = fields.Float("Total volume")
    uom_id = fields.Many2one(related="product_id.uom_id", string="Product UOM")
    to_be_ordered_in_purchase_uom = fields.Integer("To Be Ordered In Purchase UoM")
    uom_po_id = fields.Many2one(related="product_id.uom_po_id", string="Purchase UOM")
