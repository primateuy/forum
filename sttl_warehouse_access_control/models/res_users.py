# -*- coding: utf-8 -*-
from email.policy import default

from odoo import models, fields,api
from odoo.addons.base.models.ir_actions_report import process
from odoo.exceptions import UserError


# inherited res.users model to extend it and add allowed_location_ids field.
class ResUsers(models.Model):
    _inherit = 'res.users'
    allowed_warehouse_ids = fields.Many2many('stock.warehouse', string='Available Warehouses')
    allowed_location_ids = fields.Many2many('stock.location', string='Available Locations',
                                            domain="['|',('warehouse_id','in',allowed_warehouse_ids),('warehouse_id','=',False)]")
    allowed_operation_types = fields.Many2many('stock.picking.type',string='Operation Types',domain="[('warehouse_id','in',allowed_warehouse_ids)]")
    check_warehouse = fields.Boolean(string='Check warehouse',compute='check_warehouse_update',store=True)
    check_location = fields.Boolean(string='Check location',compute='check_location_update',store=True)
    check_operation = fields.Boolean(string='Check operation',compute='check_operation_update',store=True)
    @api.onchange('allowed_warehouse_ids')
    def change_location_on_change_warehouse(self):
        if not self.allowed_warehouse_ids:
            self.allowed_location_ids = False
            self.allowed_operation_types = False
            return
        warehouse_ids = self.allowed_warehouse_ids.ids
        view_locations = self.env['stock.location'].search([
            ('warehouse_id', 'in', warehouse_ids),
            ('usage', '=', 'view')
        ]).ids


        additional_locations = self.allowed_location_ids.filtered(
            lambda loc: not loc.warehouse_id or loc.warehouse_id.id in warehouse_ids
        ).ids

        filtered_operation = []
        print(self.allowed_operation_types, 'ids of warehouse')
        for i in self.allowed_operation_types:
            print('inside loop')
            if i.warehouse_id.id in self.allowed_warehouse_ids.ids:
                print(i.warehouse_id, i, 'warehouse id in llop')
                filtered_operation.append(i.id)

        filtered_locations = list(set(view_locations + additional_locations))
        self.allowed_location_ids = [(6, 0, filtered_locations)]
        self.allowed_operation_types = [(6,0,filtered_operation)]

    @api.depends('allowed_warehouse_ids')
    def check_warehouse_update(self):
        for rec in self:
            print(rec.allowed_warehouse_ids,'aloooooooooooooooooooooooooooooooo')
            if len(rec.allowed_warehouse_ids.ids) == 0:
                print('length less')
                rec.check_warehouse = False
            else:
                print('length more')
                rec.check_warehouse = True

    @api.depends('allowed_location_ids')
    def check_location_update(self):
        for rec in self:
            print(rec.allowed_location_ids,'locaaaaaaaaaaaaaaaa')
            if len(rec.allowed_location_ids.ids) == 0:
                rec.check_location = False
            else:
                print('length more')
                rec.check_location = True

    @api.depends('allowed_operation_types')
    def check_operation_update(self):
        for rec in self:
            print(rec.allowed_operation_types,'opppppppppppp')
            if len(rec.allowed_operation_types.ids) == 0:
                rec.check_operation = False
            else:
                print('length more')
                rec.check_operation = True


    def write(self, values):
        res = super(ResUsers, self).write(values)
        flag=1
        list_of_locations=[]
        list_of_warehouses=[]
        for location in self.allowed_location_ids:
                list_of_locations.append(location['warehouse_id'].id)
                if location['warehouse_id'] and location['location_id'].id ==1 :
                    list_of_warehouses.append(location['warehouse_id'].id)
        for warehouse in list_of_locations:
            if warehouse:
                if warehouse not in list_of_warehouses:
                    flag=0

        if flag == 0:
            raise UserError('You need warehouse access to view/manage stock in this location')
        self.clear_caches()
        return res
