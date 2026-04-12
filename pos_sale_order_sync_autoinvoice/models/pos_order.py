import logging
from odoo import models

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = "pos.order"

    def create_sale_order_from_pos(self):
        """
        Extiende create_sale_order_from_pos del módulo pos_sale_order_sync.
        Después de crear la SO, verifica si las líneas acumuladas "por facturar"
        del mismo cliente + tipo de pedido superan el límite del punto de emisión.
        Si se supera, genera una factura en borrador con todas las SO anteriores
        a la recién creada, y deja la nueva SO fuera para el próximo bloque.
        """
        super().create_sale_order_from_pos()

        for pos_order in self:
            so = pos_order.sale_order_id
            if not so:
                continue

            self._check_and_autoinvoice(so)

    def _check_and_autoinvoice(self, new_so):
        """
        Verifica si el acumulado de líneas "por facturar" del mismo cliente
        y tipo de pedido supera el límite del punto de emisión.
        Si es así, genera una factura en borrador con todas las SO anteriores
        a new_so (la recién creada queda fuera).
        """
        tipo_pedido = new_so.type_id
        if not tipo_pedido:
            _logger.debug(
                "[autoinvoice] SO %s sin tipo de pedido, se omite control de límite.",
                new_so.name,
            )
            return

        # Obtener el límite desde la cadena: tipo_pedido → diario → punto de emisión
        max_lineas = self._get_max_lineas(tipo_pedido)
        if not max_lineas:
            _logger.debug(
                "[autoinvoice] No se encontró max_numero_lineas para tipo de pedido %s, se omite.",
                tipo_pedido.name,
            )
            return

        partner = new_so.partner_id

        # Buscar todas las SO "por facturar" del mismo cliente y tipo de pedido,
        # ordenadas por fecha de creación, excluyendo la recién creada.
        sos_por_facturar = self.env["sale.order"].search(
            [
                ("partner_id", "=", partner.id),
                ("type_id", "=", tipo_pedido.id),
                ("invoice_status", "=", "to invoice"),
                ("id", "!=", new_so.id),
                ("company_id", "=", new_so.company_id.id),
            ],
            order="date_order asc",
        )

        if not sos_por_facturar:
            return

        lineas_anteriores = sum(sos_por_facturar.mapped("numero_lineas"))
        lineas_nuevas = new_so.numero_lineas
        total_lineas = lineas_anteriores + lineas_nuevas

        _logger.info(
            "[autoinvoice] cliente=%s tipo=%s | anteriores=%s nueva=%s total=%s limite=%s",
            partner.name,
            tipo_pedido.name,
            lineas_anteriores,
            lineas_nuevas,
            total_lineas,
            max_lineas,
        )

        if total_lineas <= max_lineas:
            return

        # El total supera el límite: facturar solo las SO anteriores.
        # La SO nueva queda fuera para el próximo bloque.
        _logger.info(
            "[autoinvoice] Límite superado. Generando factura en borrador para %s SO "
            "(cliente=%s, tipo=%s).",
            len(sos_por_facturar),
            partner.name,
            tipo_pedido.name,
        )
        self._create_draft_invoice(sos_por_facturar, tipo_pedido)

    def _get_max_lineas(self, tipo_pedido):
        """
        Recorre la cadena tipo_pedido → journal_id → punto_emision_id → max_numero_lineas.
        Devuelve el límite como entero, o None si no está configurado.
        """
        journal = getattr(tipo_pedido, "journal_id", None)
        if not journal:
            return None

        punto_emision = getattr(journal, "punto_emision_id", None)
        if not punto_emision:
            return None

        max_lineas = getattr(punto_emision, "max_numero_lineas", None)
        if not max_lineas or max_lineas <= 0:
            return None

        return max_lineas

    def _create_draft_invoice(self, sale_orders, tipo_pedido):
        """
        Genera una factura en borrador agrupando las sale_orders recibidas,
        usando el wizard estándar de Odoo (sale.advance.payment.inv).
        La factura queda en estado borrador para revisión antes de confirmarse.
        """
        try:
            wizard = self.env["sale.advance.payment.inv"].with_context(
                active_ids=sale_orders.ids,
                active_model="sale.order",
                active_id=sale_orders[0].id,
            ).create({
                "advance_payment_method": "delivered",
            })
            wizard.create_invoices()

            # Dejar la factura en borrador (el wizard la confirma por defecto en algunos casos)
            # Buscar las facturas recién creadas vinculadas a estas SO y resetearlas a borrador.
            invoices = sale_orders.mapped("invoice_ids").filtered(
                lambda inv: inv.state == "posted" and inv.move_type == "out_invoice"
            )
            for inv in invoices:
                inv.button_draft()

            _logger.info(
                "[autoinvoice] Factura(s) en borrador generada(s): %s",
                invoices.mapped("name"),
            )

        except Exception as e:
            _logger.error(
                "[autoinvoice] Error al generar factura en borrador: %s", str(e)
            )
