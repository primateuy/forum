from odoo import models, fields
from odoo.exceptions import UserError

class LandedCost(models.Model):
    _inherit = 'stock.landed.cost'
    import_op_in_draft = fields.Char(compute='_compute_import_op_in_draft')
    has_import_op_in_draft = fields.Boolean(compute='_compute_has_import_op_in_draft')
    has_import_op_in_open_status = fields.Boolean(compute='_compute_has_import_op_in_open_status')

    def _compute_import_op_in_draft(self):

        all_ids = [x.id for x in self.picking_ids]

        if len(all_ids) != 0:
            self.env.cr.execute("""SELECT sp.name, slc.name FROM stock_landed_cost AS slc
                                INNER JOIN stock_landed_cost_stock_picking_rel AS slc_sp ON slc.id = slc_sp.stock_landed_cost_id
                                INNER JOIN stock_picking AS sp on slc_sp.stock_picking_id = sp.id
                                WHERE slc.state = 'draft' AND slc.id != """ + str(self.id) + """ AND 
                                slc_sp.stock_picking_id IN %s """, [tuple(all_ids)])

            ids_in_draft = ', '.join([str(item[0]) + ' (' + str(item[1]) +')' for item in self.env.cr.fetchall()])
        else:
            ids_in_draft = ''
        
        if ids_in_draft == '':
            self.import_op_in_draft = 'No'
        else:
            self.import_op_in_draft = ids_in_draft
        
        return True
    
    def _compute_has_import_op_in_open_status(self):

        all_ids = [x.id for x in self.picking_ids]

        if len(all_ids) != 0:
            self.env.cr.execute("""SELECT 1 FROM stock_landed_cost AS slc
                                INNER JOIN stock_landed_cost_stock_picking_rel AS slc_sp ON slc.id = slc_sp.stock_landed_cost_id
                                INNER JOIN stock_picking AS sp on slc_sp.stock_picking_id = sp.id
                                WHERE sp.import_op_status = 'open' AND 
                                slc_sp.stock_picking_id IN %s """, [tuple(all_ids)])
        
            self.has_import_op_in_open_status = bool(self.env.cr.fetchone())
        else :
            self.has_import_op_in_open_status = False
        return True

    def _compute_has_import_op_in_draft(self):
        self.has_import_op_in_draft = self.import_op_in_draft != 'No'
        return True
    
    def action_close_import_status(self):

        if (self.has_import_op_in_draft):
            raise UserError('No es posible cerrar las Transferencias. Revise las Transferencias en Costes en Destino en estado "borrador".')
        else:
            all_ids = [x.id for x in self.picking_ids]
            pickings = self.env['stock.picking'].browse(all_ids)
            for p in pickings:
                p.import_op_status = 'closed'
        return {
            'effect': {
            'fadeout': 'slow',
            'message': "Se cerraron todas las Transferencias",
            'img_url': '/web/static/src/img/smile.svg',
            'type': 'rainbow_man',
            }
        }
