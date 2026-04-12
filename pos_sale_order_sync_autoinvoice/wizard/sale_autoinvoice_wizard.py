import logging
from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleAutoinvoiceWizard(models.TransientModel):
    _name = "sale.autoinvoice.wizard"
    _description = "Facturación automática por límite de líneas"

    sale_order_ids = fields.Many2many(
        "sale.order",
        string="Órdenes seleccionadas",
        readonly=True,
    )
    orders_to_invoice_ids = fields.Many2many(
        "sale.order",
        "sale_autoinvoice_to_invoice_rel",
        string="Órdenes a facturar",
        readonly=True,
    )
    orders_excluded_ids = fields.Many2many(
        "sale.order",
        "sale_autoinvoice_excluded_rel",
        string="Órdenes excluidas",
        readonly=True,
    )
    lines_to_invoice = fields.Integer("Líneas a facturar", readonly=True)
    lines_excluded = fields.Integer("Líneas excluidas", readonly=True)
    orders_excluded_count = fields.Integer("Órdenes excluidas", readonly=True)
    max_lineas = fields.Integer("Límite de líneas", readonly=True)
    warning_message = fields.Text("Resumen", readonly=True)
    has_exclusions = fields.Boolean(readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        active_ids = self.env.context.get("active_ids", [])
        sale_orders = self.env["sale.order"].browse(active_ids).filtered(
            lambda so: so.invoice_status == "to invoice"
        )

        if not sale_orders:
            raise UserError("No hay órdenes de venta 'por facturar' en la selección.")

        # Verificar que todas tengan el mismo tipo de pedido
        tipos = sale_orders.mapped("type_id")
        if len(tipos) > 1:
            raise UserError(
                "Las órdenes seleccionadas tienen distintos tipos de pedido. "
                "Seleccioná solo órdenes del mismo tipo."
            )

        tipo = tipos[0] if tipos else False
        max_lineas = self._get_max_lineas(tipo)

        if not max_lineas:
            raise UserError(
                "No se encontró un límite de líneas configurado en el punto de emisión "
                "del diario del tipo de pedido '%s'." % (tipo.name if tipo else "")
            )

        # Ordenar por fecha de creación
        sale_orders = sale_orders.sorted(key=lambda so: so.date_order)

        # Acumular hasta el límite
        acumulado = 0
        to_invoice = self.env["sale.order"]
        excluded = self.env["sale.order"]

        for so in sale_orders:
            if acumulado + so.numero_lineas <= max_lineas:
                acumulado += so.numero_lineas
                to_invoice |= so
            else:
                excluded |= so

        lines_excluded = sum(excluded.mapped("numero_lineas"))

        if not to_invoice:
            raise UserError(
                "La primera orden ya supera el límite de %s líneas. "
                "No es posible generar la factura." % max_lineas
            )

        has_exclusions = bool(excluded)

        if has_exclusions:
            warning_message = (
                "Se facturarán %s órdenes con %s líneas en total.\n"
                "Quedarán fuera %s órdenes con %s líneas que superan el límite de %s."
            ) % (
                len(to_invoice),
                acumulado,
                len(excluded),
                lines_excluded,
                max_lineas,
            )
        else:
            warning_message = (
                "Se facturarán %s órdenes con %s líneas en total. "
                "Todas las órdenes entran dentro del límite de %s líneas."
            ) % (len(to_invoice), acumulado, max_lineas)

        res.update({
            "sale_order_ids": [(6, 0, sale_orders.ids)],
            "orders_to_invoice_ids": [(6, 0, to_invoice.ids)],
            "orders_excluded_ids": [(6, 0, excluded.ids)],
            "lines_to_invoice": acumulado,
            "lines_excluded": lines_excluded,
            "orders_excluded_count": len(excluded),
            "max_lineas": max_lineas,
            "warning_message": warning_message,
            "has_exclusions": has_exclusions,
        })

        return res

    def _get_max_lineas(self, tipo_pedido):
        if not tipo_pedido:
            return None
        journal = tipo_pedido.journal_id
        if not journal:
            return None
        punto_emision = journal.punto_emision_id
        if not punto_emision:
            return None
        max_lineas = punto_emision.max_numero_lineas
        if not max_lineas or max_lineas <= 0:
            return None
        return max_lineas

    def action_create_invoice(self):
        """Genera la factura en borrador con las órdenes que entran en el límite."""
        sale_orders = self.orders_to_invoice_ids
        if not sale_orders:
            raise UserError("No hay órdenes para facturar.")

        wizard = self.env["sale.advance.payment.inv"].with_context(
            active_ids=sale_orders.ids,
            active_model="sale.order",
            active_id=sale_orders[0].id,
            autoinvoice_bypass_line_limit=True,
        ).create({
            "advance_payment_method": "delivered",
        })
        wizard.create_invoices()

        # Asegurar que la factura quede en borrador
        invoices = sale_orders.mapped("invoice_ids").filtered(
            lambda inv: inv.move_type == "out_invoice"
        )
        for inv in invoices.filtered(lambda i: i.state == "posted"):
            inv.button_draft()

        _logger.info(
            "[autoinvoice] Factura(s) en borrador: %s | SO facturadas: %s | SO excluidas: %s",
            invoices.mapped("name"),
            sale_orders.mapped("name"),
            self.orders_excluded_ids.mapped("name"),
        )

        # Mostrar las facturas generadas
        return {
            "type": "ir.actions.act_window",
            "name": _("Facturas generadas"),
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", invoices.ids)],
            "target": "current",
        }
