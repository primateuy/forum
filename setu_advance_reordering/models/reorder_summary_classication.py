from odoo import fields, models, api, _


class ReorderSummaryClassification(models.Model):
    _name = 'reorder.summary.classification'

    product_id = fields.Many2one('product.product', string='Product')
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse')
    turnover_ratio = fields.Float('Turnover Ratio')
    fsn_classification = fields.Char("FSN")
    reorder_process_id = fields.Many2one('advance.reorder.orderprocess', string='Advance reorder process')
    procurement_process_id = fields.Many2one('advance.procurement.process', string="Replenishment process")

    def get_reorder_classification(self, products, warehouses, start_date, end_date):
        query = """Select product_id,warehouse_id,turnover_ratio,stock_movement
                from get_inventory_fsn_analysis_report('%s','%s','%s','%s','%s','%s', '%s')
                """ % ('{}', products, '{}', warehouses, start_date, end_date, 'all')
        self._cr.execute(query)
        return self._cr.dictfetchall()

    def prepare_reorder_classification(self, products, warehouses, start_date, end_date,
                                       reorder_classification_ids):
        reorder_classification = self.get_reorder_classification(products, warehouses, start_date, end_date)
        vals = []
        for data in reorder_classification:
            classification_vals = {'product_id': data.get('product_id'),
                                   'warehouse_id': data.get('warehouse_id'),
                                   'turnover_ratio': data.get('turnover_ratio'),
                                   'fsn_classification': data.get('stock_movement')}

            cline_id = reorder_classification_ids.filtered(lambda x: x.product_id.id == data.get('product_id')
                                                                     and x.warehouse_id.id == data.get('warehouse_id'))
            if cline_id:
                cline_id.write(classification_vals)
                continue
            vals.append((0, 0, classification_vals))
        return vals
