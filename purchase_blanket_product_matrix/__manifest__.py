# -*- coding: utf-8 -*-
{
    "name": "Purchase Blanket: Variant Matrix + Totals + Quantity Control",
    "version": "17.0.1.0.1",
    "category": "Purchase",
    "summary": "Variant matrix on Blanket Orders (purchase.requisition), totals and PO quantity overrun control",
    "author": "PrimateUy",
    "license": "LGPL-3",
    "depends": [
        "purchase_requisition",
        "purchase_product_matrix",
    ],
    "data": [
        "security/ir.model.access.csv",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
