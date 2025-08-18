
# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

def _clean(s):
    return (s or "").strip().upper().replace(" ", "")

class ProductCodeDomain(models.Model):
    _name = "product.code.domain"
    _description = "Dominio/campo de código adicional"
    _order = "name"

    name = fields.Char(required=True, translate=False)
    code = fields.Char(required=True, size=20)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("code_unique", "unique(code)", "El código del dominio debe ser único."),
    ]

class ProductCategory(models.Model):
    _inherit = "product.category"

    code = fields.Char(string="Código", help="Código de la categoría para usar en el código automático.")

class ProductAttribute(models.Model):
    _inherit = "product.attribute"

    include_in_code = fields.Boolean(string="Incluir en código automático", default=False,
                                     help="Si está activo, los valores de este atributo se concatenarán al código.")
    sequence = fields.Integer(default=10, help="Orden de concatenación cuando se incluyan en el código.")

class ProductAttributeValue(models.Model):
    _inherit = "product.attribute.value"

    code = fields.Char(string="Código de valor", help="Código corto del valor para usar en el código automático.")

class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    product_code_total_length = fields.Integer(string="Largo total del código (plantilla)", default=10,
                                               help="Cantidad total de caracteres del código de plantilla (sin variantes).")
    product_code_template_auto = fields.Boolean(string="Codificar plantillas automáticamente", default=True)
    product_code_variants_auto = fields.Boolean(string="Codificar variantes automáticamente", default=True)
    product_code_enforce_unique = fields.Boolean(string="Exigir unicidad de código", default=False)

    def set_values(self):
        res = super().set_values()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('product_auto_code.total_length', self.product_code_total_length or 0)
        ICP.set_param('product_auto_code.template_auto', bool(self.product_code_template_auto))
        ICP.set_param('product_auto_code.variants_auto', bool(self.product_code_variants_auto))
        ICP.set_param('product_auto_code.enforce_unique', bool(self.product_code_enforce_unique))
        return res

    @api.model
    def get_values(self):
        res = super().get_values()
        ICP = self.env['ir.config_parameter'].sudo()
        res.update(
            product_code_total_length = int(ICP.get_param('product_auto_code.total_length', default="10") or 10),
            product_code_template_auto = ICP.get_param('product_auto_code.template_auto', default="True") == "True",
            product_code_variants_auto = ICP.get_param('product_auto_code.variants_auto', default="True") == "True",
            product_code_enforce_unique = ICP.get_param('product_auto_code.enforce_unique', default="False") == "True",
        )
        return res

class ProductTemplate(models.Model):
    _inherit = "product.template"

    code_domain_id = fields.Many2one("product.code.domain", string="Dominio de código")
    auto_code = fields.Boolean(string="Código automático", default=True,
                               help="Si está activo y la opción global lo permite, se generará el código al crear/editar.")
    code_prefix = fields.Char(string="Prefijo calculado", compute="_compute_code_prefix", store=True)
    default_code = fields.Char(string="Referencia interna", index=True)

    @api.depends('categ_id.code', 'code_domain_id.code')
    def _compute_code_prefix(self):
        for rec in self:
            rec.code_prefix = _clean(rec.categ_id.code) + _clean(rec.code_domain_id.code)

    # --- Helpers de parámetros globales ---
    def _get_total_length(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return int(ICP.get_param('product_auto_code.total_length', default="10") or 10)

    def _get_template_auto(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return ICP.get_param('product_auto_code.template_auto', default="True") == "True"

    def _get_variants_auto(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return ICP.get_param('product_auto_code.variants_auto', default="True") == "True"

    # --- Core build ---
    def _ensure_components(self):
        for rec in self:
            if not _clean(rec.categ_id.code):
                raise UserError(_("La categoría '%s' no tiene código configurado.") % (rec.categ_id.display_name,))
            if not rec.code_domain_id or not _clean(rec.code_domain_id.code):
                raise UserError(_("Debe seleccionar el dominio de código y definir su 'Código'."))

    def _get_or_create_seq(self, prefix, padding):
        """Devuelve/crea ir.sequence específica para el prefijo dado"""
        seq_code = f"product.auto.code.{prefix}"
        seq = self.env['ir.sequence'].sudo().search([('code', '=', seq_code)], limit=1)
        if not seq:
            seq = self.env['ir.sequence'].sudo().create({
                'name': f"Códigos {prefix}",
                'code': seq_code,
                'prefix': '',
                'padding': padding,
                'implementation': 'no_gap',
            })
        else:
            if seq.padding != padding:
                seq.padding = padding
        return seq

    def _build_prefix(self):
        self.ensure_one()
        return _clean(self.categ_id.code) + _clean(self.code_domain_id.code)

    def _generate_template_code(self):
        self.ensure_one()
        self._ensure_components()
        total_len = self._get_total_length()
        prefix = self._build_prefix()
        if len(prefix) >= total_len:
            return prefix[:total_len]
        padding = total_len - len(prefix)
        seq = self._get_or_create_seq(prefix, padding)
        seq_part = seq.next_by_code(seq.code)
        return prefix + seq_part

    def _variant_attrs_ordered(self):
        self.ensure_one()
        return self.attribute_line_ids.mapped('attribute_id').filtered(lambda a: a.include_in_code).sorted(key=lambda a: (a.sequence, a.id))

    def _compute_variant_suffix(self, variant):
        self.ensure_one()
        suffix_vals = []
        for attr in self._variant_attrs_ordered():
            val = variant.product_template_attribute_value_ids.filtered(lambda v: v.attribute_id.id == attr.id)[:1]
            if val:
                suffix_vals.append(_clean(val.product_attribute_value_id.code))
        return "".join(suffix_vals)

    def _generate_code_for_variant(self, variant):
        self.ensure_one()
        prefix = self.default_code or self._generate_template_code()
        code = prefix + self._compute_variant_suffix(variant)
        total_len = self._get_total_length()
        if len(code) < total_len:
            padding = total_len - len(code)
            seq = self._get_or_create_seq(code, padding)
            code = code + seq.next_by_code(seq.code)
        variant.default_code = code

    def _generate_variant_codes(self):
        for tmpl in self:
            for pv in tmpl.product_variant_ids:
                tmpl._generate_code_for_variant(pv)

    # --- Hooks de create/write ---
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.auto_code and rec._get_template_auto():
                rec.default_code = rec._generate_template_code()
        to_variants = records.filtered(lambda r: r._get_variants_auto())
        to_variants._generate_variant_codes()
        return records

    def write(self, vals):
        res = super().write(vals)
        interesting = {'categ_id', 'code_domain_id', 'auto_code'}
        if interesting & set(vals.keys()):
            for rec in self:
                if rec.auto_code and rec._get_template_auto():
                    rec.default_code = rec._generate_template_code()
                    if rec._get_variants_auto():
                        rec._generate_variant_codes()
        return res

    # --- Acciones manuales ---
    def action_generate_template_code(self):
        for rec in self:
            rec.default_code = rec._generate_template_code()
        return True

    def action_generate_variant_codes(self):
        for rec in self:
            rec._generate_variant_codes()
        return True

    def action_generate_codes(self):
        self.action_generate_template_code()
        self.action_generate_variant_codes()
        return True

class ProductProduct(models.Model):
    _inherit = "product.product"

    def action_generate_code(self):
        for rec in self:
            rec.product_tmpl_id._generate_code_for_variant(rec)
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.product_tmpl_id and rec.product_tmpl_id._get_variants_auto():
                rec.product_tmpl_id._generate_code_for_variant(rec)
        return records
