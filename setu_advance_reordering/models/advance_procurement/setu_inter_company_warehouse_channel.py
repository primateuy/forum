from datetime import datetime
from odoo import fields, models, api, _


class SetuIntercomapnyChannel(models.Model):
    _inherit = 'setu.intercompany.channel'

    procurement_lead_days = fields.Integer('Lead days',
                                           help="Lead Days will be in Replenishment from Warehouses Configuration")

    def prepare_intercompany_vals_from_adv(self, requestor_warehouse, inter_company_channel_id, data={}):
        ict_vals = {
            'ict_date': datetime.today(),
            'requestor_warehouse_id': requestor_warehouse.id,
            'fulfiller_warehouse_id': inter_company_channel_id.fulfiller_warehouse_id and
                                      inter_company_channel_id.fulfiller_warehouse_id.id or False,
            # 'direct_deliver_to_customer': inter_company_channel_id.direct_deliver_to_customer,
            'manage_lot_serial': inter_company_channel_id.manage_lot_serial,
            'auto_workflow_id': inter_company_channel_id.auto_workflow_id and
                                inter_company_channel_id.auto_workflow_id.id or False,
            'intercompany_channel_id': inter_company_channel_id.id,
            'pricelist_id': inter_company_channel_id.pricelist_id and
                            inter_company_channel_id.pricelist_id.id or False,
            'sales_team_id': inter_company_channel_id.sales_team_id and
                             inter_company_channel_id.sales_team_id.id or False,
            'ict_user_id': inter_company_channel_id.ict_user_id and
                           inter_company_channel_id.ict_user_id.id or False,
            'transfer_type': 'inter_company',
            'state': 'draft',
        }
        data and ict_vals.update(data)
        return ict_vals


class SetuInterwarehouseChannel(models.Model):
    _inherit = 'setu.interwarehouse.channel'

    procurement_lead_days = fields.Integer('Lead Days',
                                           help="Lead Days will be in Replenishment from Warehouses Configuration")

    def prepare_interwarehouse_values(self, requestor_warehouse, inter_warehouse_channel_id, data={}):
        iwt_vals = {
            'ict_date': datetime.today(),
            'requestor_warehouse_id': requestor_warehouse.id,
            'fulfiller_warehouse_id': inter_warehouse_channel_id.fulfiller_warehouse_id
                                      and inter_warehouse_channel_id.fulfiller_warehouse_id.id or False,
            'interwarehouse_channel_id': inter_warehouse_channel_id.id,
            'ict_user_id': inter_warehouse_channel_id.ict_user_id
                           and inter_warehouse_channel_id.ict_user_id.id or False,
            'transfer_type': 'inter_warehouse',
            'state': 'draft',
            'transfer_with_single_picking': inter_warehouse_channel_id.transfer_with_single_picking,
            'location_id': self.location_id and self.location_id.id or False,
        }
        data and iwt_vals.update(data)
        return iwt_vals
