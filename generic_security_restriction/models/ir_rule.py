import logging

from odoo import api, models, tools
from odoo.osv import expression
from odoo.tools import config
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class IrRule(models.Model):
    _inherit = 'ir.rule'

    def _gsr__model_restriction__domain(self, model_name, mode):
        if mode == 'read':
            mode_domain = [('apply_mode_read', '=', True)]
        elif mode == 'write':
            mode_domain = [('apply_mode_write', '=', True)]
        elif mode == 'create':
            mode_domain = [('apply_mode_create', '=', True)]
        elif mode == 'unlink':
            mode_domain = [('apply_mode_unlink', '=', True)]
        else:
            # Unknown mode, do nothing
            return []

        restriction_rules_domain = expression.AND([
            mode_domain,
            [('model_name', '=', model_name)],
            [('active', '=', True)],
            expression.OR([
                [('user_ids.id', '=', self.env.user.id)],
                [('group_ids.users.id', '=', self.env.user.id)],
            ]),
        ])

        # Find restriction rules
        rules = self.sudo().env['generic.security.model.restriction'].search(
            restriction_rules_domain)
        if not rules:
            return []

        eval_context = self._eval_context()

        # Compute restrictive domains to be applied
        restriction_domains = []
        for rule in rules:
            domain = rule._get_restriction_domain()
            dom = safe_eval(domain, eval_context) if domain else []
            dom = expression.normalize_domain(dom)
            restriction_domains += [dom]

        return expression.AND(restriction_domains)

    @api.model
    @tools.conditional(
        'xml' not in config['dev_mode'],
        tools.ormcache('self.env.uid', 'self.env.su', 'model_name', 'mode',
                       'tuple(self._compute_domain_context_values())'),
    )
    def _compute_domain(self, model_name, mode="read"):
        domain = super(IrRule, self)._compute_domain(model_name, mode=mode)

        if self.env.su:
            return domain

        model_restriction_domain = self._gsr__model_restriction__domain(
            model_name=model_name, mode=mode)
        return expression.AND([
            domain,
            model_restriction_domain,
        ])
