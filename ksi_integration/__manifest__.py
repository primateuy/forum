{
    "name": "Integración Cámaras KSI",
    "version": "17.0.0.0",
    "category": "Point of Sale",
    "summary": "Integración de tráfico de personas desde KSI Vision",
    "author": "ANDRES",
    "depends": ["base", "account", "point_of_sale"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",

        "views/account_journal_views.xml",
        "views/ksi_traffic_views.xml",
        "views/menu.xml",

        "data/ir_cron.xml",
        "data/token.xml",
    ],
    "installable": True,
    "application": False,
}
