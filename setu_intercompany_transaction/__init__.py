from . import wizard
from . import models
from odoo import api, SUPERUSER_ID

def pre_init(cr):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['res.company'].search([]).mapped("partner_id").write({'company_id' : False})
    # env['product.product'].search([]).write({'company_id': False})
    # cr.execute("update product_product set company_id = False")