from odoo import fields, models, api, _


class AdvanceProcurementProcessSummary(models.Model):
    _name = 'advance.procurement.process.summary'
    _description = "Advance Procurement Summary"

    def _default_weight_uom_name(self):
        weight_uom = self.env['product.template']._get_weight_uom_id_from_ir_config_parameter()
        return weight_uom and weight_uom.name or ''

    product_id = fields.Many2one('product.product', string="Product")
    product_volume = fields.Float('Volume', related='product_id.volume')
    volume_uom_name = fields.Char('Volume UOM', related='product_id.volume_uom_name')
    product_weight = fields.Float('Weight', related='product_id.weight')
    weight_uom_name = fields.Char('Weight UOM', default=_default_weight_uom_name)
    warehouse_demand_qty = fields.Integer("Own Demand", help='Demand of configure warehouse in '
                                                             'Replenishment from Warehouse')
    demanded_qty = fields.Integer("Replenish Demand", help="Demand of other warehouse configure "
                                                           "in Configuration tab")
    available_qty = fields.Integer("Free to replenish", help='Available Quantity - Outgoing')
    order_qty = fields.Integer("To be replenished", help='Product Quantity delivered to another warehouse')
    total_volume = fields.Float("Total volume")
    procurement_process_id = fields.Many2one('advance.procurement.process', string="Replenishment process")
