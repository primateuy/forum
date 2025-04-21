from odoo import fields, models, api, _


class ReorderStockMovementReport(models.Model):
    _name = 'reorder.stock.movement.report'

    product_id = fields.Many2one('product.product', string='Product')
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse')
    opening_stock = fields.Float('Opening Stock')
    sales = fields.Float('Sales')
    sales_return = fields.Float('Sales Return')
    purchase = fields.Float('Purchase')
    purchase_return = fields.Float('Purchase Return')
    internal_in = fields.Float('Internal In')
    internal_out = fields.Float('Internal Out')
    adjustment_in = fields.Float('Adjustment In')
    adjustment_out = fields.Float('Adjustment Out')
    production_in = fields.Float('Production In')
    production_out = fields.Float('Production Out')
    transit_in = fields.Float('Transit In')
    transit_out = fields.Float('Transit Out')
    closing_stock = fields.Float('Closing')
    reorder_process_id = fields.Many2one('advance.reorder.orderprocess', string='Advance reorder process')
    procurement_process_id = fields.Many2one('advance.procurement.process', string="Replenishment process")

    def get_procurement_stock_movement_report(self, products, warehouses, start_date, end_date):
        # products = self.product_ids and set(self.product_ids.ids) or {}
        # warehouses = self.config_ids and set(list(set(self.config_ids.mapped('warehouse_id').ids))) or {}
        query = """Select * from get_products_stock_movements('%s','%s','%s','%s','%s','%s')
                """ % ('{}', products, '{}', warehouses, start_date, end_date)
        self._cr.execute(query)
        return self._cr.dictfetchall()

    def prepare_stock_movement_report(self, products, warehouses, start_date, end_date, procurement_stock_movement_ids):
        reorder_stock_movement = self.get_procurement_stock_movement_report(products, warehouses, start_date, end_date)
        vals = []
        for data in reorder_stock_movement:
            stock_movement_vals = {'product_id': data.get('product_id'),
                                   'warehouse_id': data.get('warehouse_id'),
                                   'opening_stock': data.get('opening_stock'),
                                   'sales': data.get('sales'),
                                   'sales_return': data.get('sales_return'),
                                   'purchase': data.get('purchase'),
                                   'purchase_return': data.get('purchase_return'),
                                   'internal_in': data.get('internal_in'),
                                   'internal_out': data.get('internal_out'),
                                   'adjustment_in': data.get('adjustment_in'),
                                   'adjustment_out': data.get('adjustment_out'),
                                   'production_in': data.get('production_in'),
                                   'production_out': data.get('production_out'),
                                   'transit_in': data.get('transit_in'),
                                   'transit_out': data.get('transit_out'),
                                   'closing_stock': data.get('closing')}

            sm_line_id = procurement_stock_movement_ids.filtered(lambda x: x.product_id.id == data.get('product_id')
                                                                           and x.warehouse_id.id == data.get(
                'warehouse_id'))
            if sm_line_id:
                sm_line_id.write(stock_movement_vals)
                continue
            vals.append((0, 0, stock_movement_vals))
        return vals
