from odoo import models, fields, api


class StockPicking(models.Model):
    _inherit = "stock.picking"
    is_import_op = fields.Boolean(string='Op. de Importación', related='picking_type_id.is_import_op')

    @api.model
    def create(self, vals):
        picking_type_id = vals.get('picking_type_id', False)

        if picking_type_id:
            picking_type = self.env['stock.picking.type'].browse(picking_type_id)

            if picking_type.is_import_op:
                vals['import_op_status'] = 'open'

        result = super(StockPicking, self).create(vals)
        return result

    import_op_status = fields.Selection(selection=[("open", "Abierta"), ("closed", "Cerrada")],
                                        string="Estado de la Carpeta")

    def action_toggle_import_status(self):
        self.ensure_one()
        if (self.import_op_status == 'open'):
            self.import_op_status = 'closed'
            text = "Transferencia cerrada correctamente."
        elif (self.import_op_status == 'closed'):
            self.import_op_status = 'open'
            text = "Transferencia abierta correctamente."
        return {
            'effect': {
                'fadeout': 'slow',
                'message': text,
                'img_url': '/web/static/src/img/smile.svg',
                'type': 'rainbow_man',
            }
        }

    def action_see_transfers(self):
        self.ensure_one()
        action = self.env.ref('stock_landed_costs.action_stock_landed_cost').read()[0]
        domain = [('picking_ids', 'in', self.id)]
        context = dict(self.env.context, default_vendor_bill_id=self.id)
        views = [(self.env.ref('stock_landed_costs.view_stock_landed_cost_tree').id, 'tree'), (False, 'form'),
                 (False, 'kanban')]
        return dict(action, domain=domain, context=context, views=views)
