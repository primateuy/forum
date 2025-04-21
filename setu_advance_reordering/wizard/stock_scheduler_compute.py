from odoo import models
import threading


class StockSchedulerCompute(models.TransientModel):
    _inherit = 'stock.scheduler.compute'

    def procure_calculation(self):
        context = self._context.copy() or {}
        context.update({'custom_order_point_function': True})
        return super(StockSchedulerCompute, self.with_context(context)).procure_calculation()
