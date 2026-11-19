# Copyright 2026 Primate (https://primate.uy)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
{
    "name": "Estado de cuenta por direccion del cliente",
    "summary": "Desglosa los estados de cuenta OCA por direccion de facturacion o de entrega",
    "version": "17.0.1.0.0",
    "category": "Accounting & Finance",
    "author": "Primate",
    "website": "https://primate.uy",
    "license": "AGPL-3",
    # fix_partner_statement (LocalizacionUy) reescribe las mismas consultas
    # para excluir las diferencias de cambio. La dependencia garantiza que
    # este modulo cargue despues y componga sobre ese SQL en vez de pisarlo.
    # En un cliente sin LocalizacionUy se puede quitar de la lista.
    "depends": ["partner_statement", "fix_partner_statement"],
    "data": [
        "wizard/statement_wizard_views.xml",
        "views/statement_templates.xml",
    ],
    "installable": True,
    "application": False,
}
