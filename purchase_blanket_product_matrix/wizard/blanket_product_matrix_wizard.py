# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PurchaseRequisitionMatrixRow(models.TransientModel):
    _name = "purchase.requisition.matrix.row"
    _description = "Purchase Agreement Matrix Row (Color x Secondary Color)"

    wizard_id = fields.Many2one("purchase.requisition.matrix.wizard", required=True, ondelete="cascade")
    name = fields.Char(required=True)
    color_value_id = fields.Many2one("product.attribute.value", required=True)
    color2_value_id = fields.Many2one("product.attribute.value", required=True)


class PurchaseRequisitionMatrixLine(models.TransientModel):
    _name = "purchase.requisition.matrix.line"
    _description = "Purchase Agreement Matrix Line"

    wizard_id = fields.Many2one("purchase.requisition.matrix.wizard", required=True, ondelete="cascade")
    row_id = fields.Many2one("purchase.requisition.matrix.row", required=True, ondelete="cascade")
    size_value_id = fields.Many2one("product.attribute.value", required=True)
    product_id = fields.Many2one("product.product", readonly=True)
    qty = fields.Float(string="Qty", default=0.0)


class PurchaseRequisitionMatrixWizard(models.TransientModel):
    _name = "purchase.requisition.matrix.wizard"
    _description = "Add Variants to Purchase Agreement (Matrix)"

    requisition_id = fields.Many2one("purchase.requisition", required=True, readonly=True)
    company_id = fields.Many2one(related="requisition_id.company_id", store=False, readonly=True)

    product_tmpl_id = fields.Many2one(
        "product.template",
        string="Producto",
        required=True,
        domain=[("purchase_ok", "=", True)],
    )

    attribute_size_id = fields.Many2one("product.attribute", string="Atributo columnas (talle)", required=True)
    attribute_color_id = fields.Many2one("product.attribute", string="Atributo filas (color)", required=True)
    attribute_color2_id = fields.Many2one("product.attribute", string="Atributo 2do color", required=True)

    row_ids = fields.One2many("purchase.requisition.matrix.row", "wizard_id", string="Rows")
    line_ids = fields.One2many("purchase.requisition.matrix.line", "wizard_id", string="Matrix lines")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_model = self.env.context.get("active_model")
        active_id = self.env.context.get("active_id")
        if active_model != "purchase.requisition" or not active_id:
            raise UserError(_("Este asistente debe abrirse desde un Acuerdo de compra."))
        res["requisition_id"] = active_id
        return res

    @api.onchange("product_tmpl_id")
    def _onchange_product_tmpl_id_set_defaults(self):
        for wiz in self:
            if not wiz.product_tmpl_id:
                continue
            attrs = wiz.product_tmpl_id.attribute_line_ids.mapped("attribute_id")

            def pick(cands):
                for a in attrs:
                    if (a.name or "").strip().lower() in cands:
                        return a
                return False

            size = pick({"talle", "talla", "size", "tamano", "tamaño"})
            color = pick({"color"})
            color2 = pick({"color secundario", "secondary color", "color2", "color 2", "combinacion", "combinación"})

            if not size and len(attrs) >= 1:
                size = attrs[0]
            if not color and len(attrs) >= 2:
                color = attrs[1]
            if not color2 and len(attrs) >= 3:
                color2 = attrs[2]

            wiz.attribute_size_id = size
            wiz.attribute_color_id = color
            wiz.attribute_color2_id = color2
            wiz._rebuild_matrix()

    @api.onchange("attribute_size_id", "attribute_color_id", "attribute_color2_id")
    def _onchange_attributes(self):
        for wiz in self:
            if wiz.product_tmpl_id and wiz.attribute_size_id and wiz.attribute_color_id and wiz.attribute_color2_id:
                wiz._rebuild_matrix()

    def _get_attribute_values(self, attribute):
        self.ensure_one()
        line = self.product_tmpl_id.attribute_line_ids.filtered(lambda l: l.attribute_id == attribute)[:1]
        return line.value_ids

    def _variant_map(self):
        self.ensure_one()
        mapping = {}
        for variant in self.product_tmpl_id.product_variant_ids:
            key = tuple(sorted(variant.product_template_attribute_value_ids.mapped("product_attribute_value_id").ids))
            mapping[key] = variant
        return mapping

    def _rebuild_matrix(self):
        for wiz in self:
            wiz.row_ids = [(5, 0, 0)]
            wiz.line_ids = [(5, 0, 0)]
            if not (wiz.product_tmpl_id and wiz.attribute_size_id and wiz.attribute_color_id and wiz.attribute_color2_id):
                continue

            size_values = wiz._get_attribute_values(wiz.attribute_size_id)
            color_values = wiz._get_attribute_values(wiz.attribute_color_id)
            color2_values = wiz._get_attribute_values(wiz.attribute_color2_id)

            if not (size_values and color_values and color2_values):
                raise UserError(_("El producto debe tener valores en los 3 atributos seleccionados."))

            row_cmds = []
            for c in color_values:
                for c2 in color2_values:
                    row_cmds.append((0, 0, {
                        "name": f"{c.display_name} • {c2.display_name}",
                        "color_value_id": c.id,
                        "color2_value_id": c2.id,
                    }))
            wiz.row_ids = row_cmds

            variant_map = wiz._variant_map()

            line_cmds = []
            for row in wiz.row_ids:
                for s in size_values:
                    key_vals = sorted([s.id, row.color_value_id.id, row.color2_value_id.id])
                    variant = variant_map.get(tuple(key_vals))
                    if not variant:
                        # fallback: variante que contenga estos 3 valores (si hay atributos extra)
                        for k, v in variant_map.items():
                            if set(key_vals).issubset(set(k)):
                                variant = v
                                break
                    line_cmds.append((0, 0, {
                        "row_id": row.id,
                        "size_value_id": s.id,
                        "product_id": variant.id if variant else False,
                        "qty": 0.0,
                    }))
            wiz.line_ids = line_cmds

    def action_confirm(self):
        self.ensure_one()
        requisition = self.requisition_id
        existing = {l.product_id.id: l for l in requisition.line_ids if l.product_id}

        for line in self.line_ids:
            if not line.product_id or not line.qty or line.qty <= 0:
                continue
            if line.product_id.id in existing:
                existing[line.product_id.id].product_qty += line.qty
            else:
                self.env["purchase.requisition.line"].create({
                    "requisition_id": requisition.id,
                    "product_id": line.product_id.id,
                    "product_qty": line.qty,
                    "product_uom_id": (line.product_id.uom_po_id.id or line.product_id.uom_id.id),
                    # precio marco: lo ajustan luego en el acuerdo
                    "price_unit": existing.get(line.product_id.id).price_unit if line.product_id.id in existing else 0.0,
                })
        return {"type": "ir.actions.act_window_close"}
