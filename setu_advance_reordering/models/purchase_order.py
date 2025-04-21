from odoo import fields, models, api, _
from datetime import datetime


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    reorder_process_id = fields.Many2one('advance.reorder.orderprocess', string="Advance Reorder Process")
    reorder_planner_id = fields.Many2one('advance.reorder.planner', string='Reorder Planner')

    # For Future functionality

    # def create_reorder(self):
    #     reorder_env = self.env['setu.advance.reorder']
    #     vals = self.prepare_reorder_vals()
    #     reorder_id = reorder_env.create(vals)
    #     reorder_id.create_reorder_line()
    #     reorder_id.write({'state': 'inprogress'})
    #     ### need to return reorder action
    #     self.write({'reorder_id': reorder_id.id})
    #     action = self.env.ref('setu_advance_reordering.setu_advance_reorder_action').read()[0]
    #     action['domain'] = [('id', '=', reorder_id.id)]
    #     return action
    #
    # def open_reorder_for_update(self):
    #     if self.reorder_id:
    #         for line in self.order_line:
    #             qty_multiple = 1 if line.reorder_line_id.qty_multiple <= 1 else line.reorder_line_id.qty_multiple
    #             line.reorder_line_id.write({
    #                 'purchase_order_qty': line.product_uom_qty,
    #                 'pack_qty': round(line.product_uom_qty / qty_multiple, 2),
    #                 'total_order_qty': line.product_uom_qty,
    #                 'suggested_stock': line.product_uom_qty})
    #         self.reorder_id.write({'state': 'inprogress'})
    #         action = self.env.ref('setu_advance_reordering.setu_advance_reorder_action').read()[0]
    #         # action['domain'] = [('id', '=', self.reorder_id.id)]
    #
    #         form_view = [(self.env.ref('setu_advance_reordering.setu_advance_reorder_form').id, 'form')]
    #         if 'views' in action:
    #             action['views'] = form_view + [(state, view) for state, view in action['views'] if view != 'form']
    #         else:
    #             action['views'] = form_view
    #         action['res_id'] = self.reorder_id.id
    #         return action
    #
    # def prepare_reorder_vals(self):
    #     return {
    #         'warehouse_id': self.picking_type_id.warehouse_id.id,
    #         'reorder_date': datetime.today(),
    #         'partner_id': self.partner_id.id,
    #         'purchase_id': self.id,
    #         'products_by_vendor': 'only_first',
    #         'user_id': self.env.user.id,
    #     }
