import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleAutoinvoiceWizard(models.TransientModel):
    _name = "sale.autoinvoice.wizard"
    _description = "Facturación automática por límite de líneas"

    sale_order_ids = fields.Many2many(
        "sale.order",
        "sale_autoinvoice_selected_rel",
        string="Órdenes seleccionadas",
        readonly=True,
    )
    orders_to_invoice_ids = fields.Many2many(
        "sale.order",
        "sale_autoinvoice_to_invoice_rel",
        string="Órdenes a facturar",
        readonly=True,
    )
    orders_skipped_ids = fields.Many2many(
        "sale.order",
        "sale_autoinvoice_skipped_rel",
        string="Órdenes salteadas",
        readonly=True,
    )
    invoice_count = fields.Integer("Facturas a emitir", readonly=True)
    orders_to_invoice_count = fields.Integer("Cantidad de órdenes a facturar", readonly=True)
    lines_to_invoice = fields.Integer("Líneas a facturar", readonly=True)
    lines_skipped = fields.Integer("Líneas salteadas", readonly=True)
    orders_skipped_count = fields.Integer("Cantidad de órdenes salteadas", readonly=True)
    max_lineas = fields.Integer("Límite de líneas", readonly=True)
    warning_message = fields.Text("Resumen", readonly=True)
    detail_message = fields.Text("Detalle por factura", readonly=True)
    has_skipped = fields.Boolean(readonly=True)

    # === Conteo de líneas =================================================

    @api.model
    def _count_invoiceable_lines(self, order, final=True):
        """Cuenta las líneas que realmente van a entrar a la factura.

        Usa el mismo `_get_invoiceable_lines()` que usa Odoo al facturar y suma
        la sección de anticipos que `_create_invoices()` agrega cuando la orden
        tiene líneas de anticipo. Contar `len(order_line)` no sirve: incluye
        secciones sin líneas facturables y líneas ya facturadas, así que no
        coincide con lo que después valida el punto de emisión.
        """
        lines = order._get_invoiceable_lines(final=final)
        count = len(lines)
        if any(line.is_downpayment for line in lines):
            count += 1  # sección "Anticipos" que agrega _create_invoices
        return count

    @api.model
    def _get_max_lineas(self, tipo_pedido):
        """Devuelve el tope de líneas del punto de emisión del tipo de pedido."""
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

    # === Armado de tandas =================================================

    @api.model
    def _pack_orders(self, sale_orders, max_lineas, final=True):
        """Reparte las órdenes en tandas que respetan el tope de líneas.

        Primero separa por clave de agrupación de factura (compañía, cliente de
        facturación, moneda y posición fiscal), porque una factura no puede
        mezclar clientes. Dentro de cada grupo arma tandas por orden de fecha:
        cada tanda acumula órdenes hasta donde entren sin pasar el tope, y
        cuando la siguiente no entra se abre una tanda nueva. Nunca se parte
        una orden entre dos facturas.

        Las órdenes que por sí solas superan el tope, o que no tienen líneas
        facturables, se saltean: se informan pero no frenan el resto.

        :return: (tandas, salteadas, lineas_por_orden) donde `tandas` es una
                 lista de recordsets — una factura por tanda.
        """
        SaleOrder = self.env["sale.order"]
        lineas_por_orden = {}
        skipped = SaleOrder
        grupos = {}

        for order in sale_orders.sorted(key=lambda so: (so.date_order, so.id)):
            n = self._count_invoiceable_lines(order, final=final)
            lineas_por_orden[order.id] = n
            # Sin líneas facturables `_create_invoices` reventaría toda la
            # transacción, así que la sacamos igual que a las sobredimensionadas.
            if n <= 0 or n > max_lineas:
                skipped |= order
                continue
            clave = (
                order.company_id.id,
                order.partner_invoice_id.id,
                order.currency_id.id,
                order.fiscal_position_id.id,
            )
            grupos.setdefault(clave, []).append(order)

        tandas = []
        for clave in sorted(grupos):
            tanda = SaleOrder
            acumulado = 0
            for order in grupos[clave]:
                n = lineas_por_orden[order.id]
                if tanda and acumulado + n > max_lineas:
                    tandas.append(tanda)
                    tanda = SaleOrder
                    acumulado = 0
                tanda |= order
                acumulado += n
            if tanda:
                tandas.append(tanda)

        return tandas, skipped, lineas_por_orden

    # === Preview ==========================================================

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        active_ids = self.env.context.get("active_ids", [])
        sale_orders = self.env["sale.order"].browse(active_ids).filtered(
            lambda so: so.invoice_status == "to invoice"
        )

        if not sale_orders:
            raise UserError(_("No hay órdenes de venta 'por facturar' en la selección."))

        # Verificar que todas tengan el mismo tipo de pedido
        tipos = sale_orders.mapped("type_id")
        if len(tipos) > 1:
            raise UserError(_(
                "Las órdenes seleccionadas tienen distintos tipos de pedido. "
                "Seleccioná solo órdenes del mismo tipo."
            ))

        tipo = tipos[0] if tipos else False
        max_lineas = self._get_max_lineas(tipo)

        if not max_lineas:
            raise UserError(_(
                "No se encontró un límite de líneas configurado en el punto de emisión "
                "del diario del tipo de pedido '%s'."
            ) % (tipo.name if tipo else ""))

        tandas, skipped, lineas_por_orden = self._pack_orders(sale_orders, max_lineas)

        if not tandas:
            raise UserError(_(
                "Ninguna de las órdenes seleccionadas se puede facturar: todas superan "
                "el límite de %s líneas del punto de emisión o no tienen líneas "
                "facturables."
            ) % max_lineas)

        to_invoice = self.env["sale.order"]
        for tanda in tandas:
            to_invoice |= tanda

        lines_to_invoice = sum(lineas_por_orden[o.id] for o in to_invoice)
        lines_skipped = sum(lineas_por_orden[o.id] for o in skipped)

        warning_message = _(
            "Se van a emitir %(facturas)s factura(s) en borrador con %(ordenes)s "
            "órdenes y %(lineas)s líneas en total, respetando el tope de "
            "%(tope)s líneas por factura."
        ) % {
            "facturas": len(tandas),
            "ordenes": len(to_invoice),
            "lineas": lines_to_invoice,
            "tope": max_lineas,
        }
        if skipped:
            warning_message += "\n" + _(
                "Quedan salteadas %(ordenes)s orden(es) con %(lineas)s líneas que no "
                "entran en ninguna factura."
            ) % {"ordenes": len(skipped), "lineas": lines_skipped}

        detalle = []
        for i, tanda in enumerate(tandas, start=1):
            lineas_tanda = sum(lineas_por_orden[o.id] for o in tanda)
            detalle.append(_(
                "Factura %(n)s: %(ordenes)s orden(es), %(lineas)s líneas — %(nombres)s"
            ) % {
                "n": i,
                "ordenes": len(tanda),
                "lineas": lineas_tanda,
                "nombres": ", ".join(tanda.mapped("name")),
            })
        for order in skipped:
            n = lineas_por_orden[order.id]
            motivo = (
                _("supera el tope de %s líneas") % max_lineas
                if n > max_lineas else _("sin líneas facturables")
            )
            detalle.append(_(
                "Salteada %(nombre)s: %(lineas)s líneas — %(motivo)s"
            ) % {"nombre": order.name, "lineas": n, "motivo": motivo})

        res.update({
            "sale_order_ids": [(6, 0, sale_orders.ids)],
            "orders_to_invoice_ids": [(6, 0, to_invoice.ids)],
            "orders_skipped_ids": [(6, 0, skipped.ids)],
            "invoice_count": len(tandas),
            "orders_to_invoice_count": len(to_invoice),
            "lines_to_invoice": lines_to_invoice,
            "lines_skipped": lines_skipped,
            "orders_skipped_count": len(skipped),
            "max_lineas": max_lineas,
            "warning_message": warning_message,
            "detail_message": "\n".join(detalle),
            "has_skipped": bool(skipped),
        })

        return res

    # === Emisión ==========================================================

    def action_create_invoice(self):
        """Emite una factura en borrador por cada tanda, hasta cubrir todas las órdenes.

        No se postea ni se toca ninguna factura existente: `_create_invoices()`
        deja las nuevas en borrador y devuelve exactamente las que creó.
        """
        self.ensure_one()
        sale_orders = self.orders_to_invoice_ids
        if not sale_orders:
            raise UserError(_("No hay órdenes para facturar."))

        max_lineas = self.max_lineas or self._get_max_lineas(sale_orders.mapped("type_id")[:1])
        if not max_lineas:
            raise UserError(_("No se encontró el límite de líneas del punto de emisión."))

        # Se recalculan las tandas al confirmar para trabajar sobre el estado
        # actual de las órdenes, no sobre el que tenían al abrir el wizard.
        tandas, skipped, lineas_por_orden = self._pack_orders(sale_orders, max_lineas)
        if not tandas:
            raise UserError(_(
                "No quedaron órdenes que entren en el límite de %s líneas."
            ) % max_lineas)

        invoices = self.env["account.move"]
        for tanda in tandas:
            # La tanda ya viene de un único grupo de facturación, así que
            # `grouped=False` produce exactamente una factura por tanda.
            invoices |= tanda._create_invoices(final=True, grouped=False)

        _logger.info(
            "[autoinvoice] tope=%s | facturas en borrador=%s (%s) | SO facturadas=%s | "
            "SO salteadas=%s",
            max_lineas,
            len(invoices),
            ", ".join(invoices.mapped("name")),
            ", ".join(sale_orders.mapped("name")),
            ", ".join(skipped.mapped("name")) or "-",
        )

        return {
            "type": "ir.actions.act_window",
            "name": _("Facturas generadas"),
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", invoices.ids)],
            "target": "current",
        }
