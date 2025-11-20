from odoo import api, SUPERUSER_ID
from odoo.addons.generic_mixin.tools.migration_utils import ensure_version


@ensure_version('0.17.0')
def migrate(cr, installed_version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    env.ref('base.user_admin').write({'allowed_use_debug_mode': True})
    env.ref('base.user_root').write({'allowed_use_debug_mode': True})
    env.ref('base.group_system').write({'allowed_use_debug_mode': True})
