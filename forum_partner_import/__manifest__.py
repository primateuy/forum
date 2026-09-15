# -*- coding: utf-8 -*-
{
    "name": "Importación masiva de clientes FORUM",
    "summary": "Carga masiva de clientes y puntos, y ajuste de inventario multi-sucursal, vía SQL por tandas",
    "version": "17.0.1.2.0",
    "author": "Primate Uy",
    "category": "Contacts",
    "license": "LGPL-3",
    "depends": [
        "contacts",
        "loyalty",
        "l10n_latam_base",
        "partner_firstname",
        "partner_contact_birthdate",
        "partner_contact_gender",
        "stock",
        "stock_account",
    ],
    "external_dependencies": {
        "python": ["openpyxl"],
    },
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/forum_import_batch_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "forum_partner_import/static/src/live_progress/live_progress.js",
            "forum_partner_import/static/src/live_progress/live_progress.xml",
        ],
    },
    "installable": True,
    "application": False,
}
