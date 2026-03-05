# -*- coding: utf-8 -*-
{
    "name": "Purchase Blanket Product Matrix",
    "summary": "Add variant matrix (grid entry) to Blanket Orders (Purchase Agreements)",
    "version": "17.0.2.0.0",
    "category": "Purchases",
    "license": "AGPL-3",
    "author": "PrimateUy",
    "depends": [
        "purchase_requisition",
        "purchase",
        "product",
        "web_widget_x2many_2d_matrix",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/purchase_requisition_views.xml",
        "wizard/blanket_product_matrix_wizard_views.xml",
    ],
    "installable": True,
    "application": False,
}
