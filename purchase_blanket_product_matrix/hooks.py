# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID

VIEW_KEY = "purchase_blanket_product_matrix.view_purchase_requisition_form_inherit_matrix"

ARCH = """<data>
    <xpath expr="//header" position="inside">
        <button name="action_open_variant_matrix"
                type="object"
                string="Agregar variantes"
                class="oe_highlight"
                attrs="{'invisible': [('state', '!=', 'draft')]}"/>
    </xpath>

    <xpath expr="//field[@name='line_ids']" position="after">
        <group col="4" class="mt16">
            <field name="total_qty" readonly="1"/>
            <field name="total_amount" readonly="1"/>
            <field name="currency_id" invisible="1"/>
        </group>
    </xpath>
</data>"""


def post_init_hook(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Find a primary form view for purchase.requisition to inherit
    base_view = env["ir.ui.view"].search([
        ("model", "=", "purchase.requisition"),
        ("type", "=", "form"),
        ("inherit_id", "=", False),
    ], order="priority asc, id asc", limit=1)
    if not base_view:
        # Fallback: any form view
        base_view = env["ir.ui.view"].search([
            ("model", "=", "purchase.requisition"),
            ("type", "=", "form"),
        ], order="priority asc, id asc", limit=1)
    if not base_view:
        return

    imd = env["ir.model.data"]
    # If already created, do nothing
    try:
        imd._xmlid_lookup(VIEW_KEY)
        return
    except Exception:
        pass

    view = env["ir.ui.view"].create({
        "name": "purchase.requisition.form.inherit.matrix (dynamic)",
        "type": "form",
        "model": "purchase.requisition",
        "inherit_id": base_view.id,
        "arch": ARCH,
        "priority": 90,
    })
    imd.create({
        "name": "view_purchase_requisition_form_inherit_matrix",
        "module": "purchase_blanket_product_matrix",
        "model": "ir.ui.view",
        "res_id": view.id,
        "noupdate": True,
    })
