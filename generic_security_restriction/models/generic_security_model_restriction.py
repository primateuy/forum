from odoo import models, fields, api, exceptions, _
from odoo.tools.safe_eval import safe_eval


class GenericSecurityModelRestrictionUser(models.Model):
    _name = 'generic.security.model.restriction'
    _description = 'Generic Security Model Restriction'
    _order = 'name ASC, id ASC'

    name = fields.Char(
        required=True,
        help='The name of restriction')
    active = fields.Boolean(
        default=True, index=True)
    model_id = fields.Many2one(
        comodel_name='ir.model',
        string='Model',
        required=True, index=True, auto_join=True,
        ondelete='cascade',
        domain=lambda self: self._get_model_id_domain())
    model_name = fields.Char(
        related='model_id.model', store=True, index=True, readonly=True,
        string="Model name")
    user_ids = fields.Many2many(
        comodel_name='res.users',
        relation='generic_security_model_restriction__user__rel',
        column1='restriction_id',
        column2='user_id',
        help="Apply this restriction to specified users.")
    group_ids = fields.Many2many(
        comodel_name='res.groups',
        relation='generic_security_model_restriction__group__rel',
        column1='restriction_id',
        column2='group_id',
        help="Apply this restriction to specified user groups.")

    domain_type = fields.Selection(
        [('simple', 'Simple'),
         ('code', 'Code')],
        default='simple', required=True,
    )
    domain_simple = fields.Text(
        required=False,
        help="Extra domain to limit the access for specific users. Simple.")
    domain_code = fields.Text(
        required=False,
        help="Extra domain to limit the access for specific users. As code.")

    apply_mode_read = fields.Boolean(
        default=True, index=True)
    apply_mode_write = fields.Boolean(
        default=True, index=True)
    apply_mode_create = fields.Boolean(
        default=True, index=True)
    apply_mode_unlink = fields.Boolean(
        default=True, index=True)

    # TODO: Make cached method to get extra domain for specific model
    # TODO: Invalidate cached methods on changes
    # TODO: Validate domain
    @api.constrains('domain_type', 'domain_simple', 'domain_code')
    def _validate_domain(self):
        eval_context = self.sudo().env['ir.rule']._eval_context()
        for record in self.sudo():
            if record.domain_type == 'simple':
                domain = record.domain_simple
            elif record.domain_type == 'code':
                domain = record.domain_code
            try:
                dom = safe_eval(domain, eval_context)
            except Exception:
                raise exceptions.ValidationError(_(
                    "Cannot parse domain for rule %(rule)s is not valid!\n"
                    "%(domain)s"
                ) % {
                    'rule': record.display_name,
                    'domain': domain,
                })

            if not isinstance(dom, (list, tuple)):
                raise exceptions.ValidationError(_(
                    "Domain for rule %(rule)s is not valid!\n%(domain)s"
                ) % {
                    'rule': record.display_name,
                    'domain': dom,
                })

    def _get_restriction_domain(self):
        self.ensure_one()

        if self.domain_type == 'simple':
            return self.domain_simple
        if self.domain_type == 'code':
            return self.domain_code
        return []

    @api.model_create_multi
    def create(self, vals_list):
        self.env['ir.rule'].clear_caches()
        return super().create(vals_list)

    def write(self, values):
        self.env['ir.rule'].clear_caches()
        return super().write(values)

    def unlink(self):
        self.env['ir.rule'].clear_caches()
        return super().unlink()

    # This method needed to create domain for 'model_id' to filter models that
    # is not abstract
    @api.model
    def _get_model_id_domain(self):
        abstract_models = [model for model, model_obj in
                           self.env.registry.models.items()
                           if model_obj._abstract]

        domain = [('model', 'not in', abstract_models)]
        return domain

    @api.onchange('model_id')
    def _onchange_model_id(self):
        for record in self:
            record.domain_simple = False
            record.domain_code = False
