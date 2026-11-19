# Copyright 2026 Primate (https://primate.uy)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""Selector de agrupamiento por direccion en el wizard de estado de cuenta."""

from odoo import api, fields, models


class StatementCommonWizard(models.AbstractModel):
    _inherit = "statement.common.wizard"

    forum_group_address = fields.Selection(
        selection=[
            ("none", "Sin agrupar (partner comercial)"),
            ("invoice", "Direccion de facturacion"),
            ("delivery", "Direccion de entrega"),
        ],
        string="Agrupar por",
        default="none",
        required=True,
        help="Emite una hoja por cada direccion del cliente en lugar de una "
        "sola por el partner comercial. Los movimientos sin direccion "
        "propia (tipicamente los pagos a cuenta) quedan en la hoja del "
        "partner comercial.",
    )

    @api.model
    def _forum_expand_partners(self, partner_ids):
        """Partner comercial de lo seleccionado, mas todas sus direcciones.

        Se sube al comercial y se vuelve a bajar a proposito, para que de lo
        mismo si el usuario selecciona la empresa padre o una sucursal
        suelta. Incluir siempre al comercial no es opcional: es lo que
        garantiza que el bucket "nivel empresa" exista y que el ELSE de la
        expresion de agrupamiento tenga a donde caer.

        Se incluyen las direcciones archivadas, porque pueden tener
        movimientos historicos dentro del periodo del reporte.
        """
        partners = self.env["res.partner"].browse(partner_ids)
        commercial = partners.commercial_partner_id
        return (
            self.env["res.partner"]
            .with_context(active_test=False)
            .search([("id", "child_of", commercial.ids)])
        )

    def _prepare_statement(self):
        res = super()._prepare_statement()
        if self.forum_group_address in ("invoice", "delivery"):
            addresses = self._forum_expand_partners(res["partner_ids"])
            res["partner_ids"] = addresses.ids
            res["forum_group_address"] = self.forum_group_address
            res["forum_address_ids"] = addresses.ids
        return res
