# -*- coding: utf-8 -*-

import logging

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    """
    Venta del PDV facturada después de cerrada la caja.

    El core ya sabe hacerlo —``_create_misc_reversal_move`` revierte la parte de
    esta venta dentro del asiento de cierre para no contabilizarla dos veces—,
    pero deja dos cosas a medio camino: el botón que lo dispara sólo se muestra
    mientras la orden está en ``paid``, y las fechas que usa son las de hoy.
    Acá se corrigen las fechas; el botón lo agrega la vista.
    """

    _inherit = "pos.order"

    # ------------------------------------------------------------------
    # Detección del caso
    # ------------------------------------------------------------------

    def _forum_es_factura_posterior(self):
        """
        La venta se está facturando después de cerrada la caja.

        El estado de la sesión es el discriminante correcto, no el de la orden:
        el core decide por ahí si tiene que revertir el asiento de cierre
        (point_of_sale/models/pos_order.py:909), y es también lo que hace que
        ``_prepare_invoice_vals`` mande la fecha a hoy.
        """
        self.ensure_one()
        return self.session_id.state == "closed" and not self.account_move

    def _forum_fecha_venta(self):
        """Fecha real de la venta, en la zona horaria del usuario."""
        self.ensure_one()
        return fields.Date.context_today(self, self.date_order)

    # ------------------------------------------------------------------
    # Fechas
    # ------------------------------------------------------------------

    def _prepare_invoice_vals(self):
        """
        Factura con la fecha de la venta, no con la de hoy.

        El core fuerza ``invoice_date = now()`` cuando la sesión ya está cerrada
        (point_of_sale/models/pos_order.py:662). Para UCFE lo que vale es la
        fecha de firma, así que la de emisión puede ser la real de la venta, y
        conviene que lo sea: los asientos de pago del PDV ya se fechan con
        ``date_order`` (point_of_sale/models/pos_payment.py:91), así que dejar
        la factura en hoy partía en dos períodos una misma operación.

        No hace falta tocar la fecha contable: ``_compute_date`` la copia de
        ``invoice_date`` en los documentos de venta
        (account/models/account_move.py:697). Y si esa fecha cae en un período
        bloqueado, ``_post`` mueve sólo la contable al primer período abierto y
        deja la de emisión donde está (account/models/account_move.py:4042): no
        hay que preverlo acá.
        """
        vals = super()._prepare_invoice_vals()
        if self._forum_es_factura_posterior():
            vals["invoice_date"] = self._forum_fecha_venta()
        return vals

    def _create_misc_reversal_move(self, payment_moves):
        """
        Fecha la reversión del cierre junto con la factura, no hoy.

        Tiene que ser la misma fecha: la reversión deshace la parte de esta
        venta dentro del asiento de cierre. Si quedara en otro período, el
        ingreso aparecería dos veces en el del cierre y en negativo en el de hoy.

        El core escribe esa fecha dentro del ``create``
        (point_of_sale/models/pos_order.py:858), así que no se puede pasar por
        parámetro. En vez de duplicar el método entero —que es largo y además
        concilia— se marca el contexto y lo aplica ``account.move.create``: el
        único asiento que se crea en esa ventana es el de reversión.
        """
        self.ensure_one()
        if self.session_id.state == "closed":
            self = self.with_context(forum_fecha_reversion=self._forum_fecha_venta())
        return super(PosOrder, self)._create_misc_reversal_move(payment_moves)

    # ------------------------------------------------------------------
    # Acción del botón
    # ------------------------------------------------------------------

    def action_pos_order_invoice(self):
        """
        Agrega al flujo del core lo que hace falta para facturar después.

        ``dont_check_dates_sequence`` es la salida que ya deja la localización
        (l10n_uy_einvoice_base/models/account_invoice.py:228) para documentos
        con fecha anterior a la del último número usado. Hace falta porque la
        factura sale con la fecha de la venta mientras el correlativo del diario
        puede estar ya en un mes posterior, y sin eso
        ``_constrains_date_sequence`` aborta el posteo
        (account/models/sequence_mixin.py:90).

        🔴 Se marca sólo para las ventas de sesiones cerradas. Es un chequeo de
        consistencia real: no se desactiva para el resto del flujo del PDV.
        """
        posteriores = self.filtered(lambda orden: orden._forum_es_factura_posterior())
        if not posteriores:
            return super().action_pos_order_invoice()

        for orden in posteriores:
            _logger.info(
                "pos_forum_factura_posterior: facturando después del cierre | "
                "venta=%s | fecha venta=%s | sesión=%s | usuario=%s",
                orden.pos_reference or orden.name,
                orden._forum_fecha_venta(),
                orden.session_id.name,
                self.env.user.login,
            )

        resultado = super(
            PosOrder,
            self.with_context(dont_check_dates_sequence=True),
        ).action_pos_order_invoice()

        posteriores._forum_dejar_constancia()
        return resultado

    def _forum_dejar_constancia(self):
        """
        Anota en la factura que se emitió después del cierre.

        Queda en el chatter para que quien la audite entienda por qué el número
        del diario es posterior a la fecha del documento. Sólo se anota si la
        factura llegó a postearse: si falló la emisión del CFE,
        ``pos_forum_cfe_pendiente`` la dejó en borrador y todavía no hay nada
        que declarar.
        """
        for orden in self:
            factura = orden.account_move
            if not factura or factura.state != "posted":
                continue
            factura.message_post(body=_(
                "Factura emitida después del cierre de caja. "
                "Venta %(venta)s del %(fecha)s, sesión %(sesion)s.",
                venta=orden.pos_reference or orden.name,
                fecha=fields.Date.to_string(orden._forum_fecha_venta()),
                sesion=orden.session_id.name,
            ))

    # ------------------------------------------------------------------
    # Facturación masiva
    # ------------------------------------------------------------------

    #: Ventas que se procesan como máximo en cada corrida. El bucle hace una
    #: llamada a UCFE por venta, y con ``limit_time_real`` en 1200 segundos una
    #: selección entera (cientos de ventas) no entra en un solo request.
    FORUM_TOPE_POR_CORRIDA = 50

    def action_forum_facturar_masivo(self):
        """
        Factura en tanda las ventas de cajas ya cerradas.

        El método del core sirve para recordsets —``_generate_pos_order_invoice``
        itera ``for order in self``— pero no aísla los errores: no tiene un solo
        ``try/except``, así que una venta que falla aborta el resto.

        🔴 Eso acá es grave, no una molestia. Uruware **commitea en medio de la
        transacción** al emitir el CFE: si la venta 30 revienta, el rollback de
        Odoo deshace las 29 facturas anteriores pero **no deshace sus CFE**, que
        ya quedaron emitidos y con numeración consumida en la DGI. Por eso se
        procesa de a una y se commitea cada una apenas sale bien: es la única
        forma de que lo ya emitido en UCFE tenga su factura en Odoo.

        La contrapartida es que la corrida no se puede deshacer a mitad de
        camino. Es deliberado.

        Las que no tienen cliente se saltean en vez de abortar: el core hace
        ``raise UserError`` con ellas (point_of_sale/models/pos_order.py:891).
        """
        seleccionadas = self
        elegibles = seleccionadas.filtered(
            lambda orden: orden._forum_es_factura_posterior()
        )
        sin_cliente = elegibles.filtered(lambda orden: not orden.partner_id)
        elegibles -= sin_cliente
        no_aplica = seleccionadas - elegibles - sin_cliente

        if not elegibles:
            return self._forum_aviso_masivo(
                titulo=_("No hay nada para facturar"),
                mensaje=self._forum_resumen_descartes(sin_cliente, no_aplica),
                exito=False,
            )

        tanda = elegibles[: self.FORUM_TOPE_POR_CORRIDA]
        quedan = len(elegibles) - len(tanda)

        emitidas = self.browse()
        fallidas = []

        for orden in tanda:
            referencia = orden.pos_reference or orden.name
            try:
                # ``generate_pdf=False`` saltea la generación del PDF y el envío
                # por correo que el core hace por cada factura
                # (point_of_sale/models/pos_order.py:906). En una tanda eso es
                # la diferencia entre minutos y horas, y nadie espera recibir
                # cientos de mails por una regularización.
                orden.with_company(orden.company_id).with_context(
                    generate_pdf=False
                ).action_pos_order_invoice()
            except Exception as error:  # noqa: BLE001 — se registra y se sigue
                self.env.cr.rollback()
                self.env.invalidate_all()
                fallidas.append((referencia, str(error).strip().splitlines()[0]))
                _logger.exception(
                    "pos_forum_factura_posterior: falló la emisión masiva | "
                    "venta=%s | usuario=%s",
                    referencia,
                    self.env.user.login,
                )
            else:
                self.env.cr.commit()
                emitidas |= orden
                _logger.info(
                    "pos_forum_factura_posterior: emitida en tanda | venta=%s | "
                    "factura=%s",
                    referencia,
                    orden.account_move.name,
                )

        return self._forum_aviso_masivo(
            titulo=_("Facturación de ventas de cajas cerradas"),
            mensaje=self._forum_resumen_masivo(
                emitidas, fallidas, sin_cliente, no_aplica, quedan
            ),
            exito=not fallidas,
        )

    def _forum_resumen_descartes(self, sin_cliente, no_aplica):
        """Texto de por qué no quedó ninguna venta para procesar."""
        partes = []
        if sin_cliente:
            partes.append(_("%s sin cliente", len(sin_cliente)))
        if no_aplica:
            partes.append(
                _("%s que no son de una caja cerrada o ya están facturadas",
                  len(no_aplica))
            )
        if not partes:
            return _("No se seleccionó ninguna venta.")
        return _("De lo seleccionado: %s.", "; ".join(partes))

    def _forum_resumen_masivo(self, emitidas, fallidas, sin_cliente, no_aplica, quedan):
        """Resumen de la corrida, para el aviso y para el log."""
        lineas = [_("Emitidas: %s.", len(emitidas))]
        if fallidas:
            lineas.append(_("Fallaron: %s.", len(fallidas)))
            for referencia, motivo in fallidas[:5]:
                lineas.append("  • %s — %s" % (referencia, motivo[:120]))
            if len(fallidas) > 5:
                lineas.append(_("  … y %s más, con el detalle en el log.",
                                len(fallidas) - 5))
        if sin_cliente:
            lineas.append(_("Salteadas por no tener cliente: %s.", len(sin_cliente)))
        if no_aplica:
            lineas.append(
                _("Ignoradas por no ser de una caja cerrada o estar ya "
                  "facturadas: %s.", len(no_aplica))
            )
        if quedan:
            lineas.append(
                _("Quedan %s para la próxima corrida (el tope es %s por vez).",
                  quedan, self.FORUM_TOPE_POR_CORRIDA)
            )
        return "\n".join(lineas)

    def _forum_aviso_masivo(self, titulo, mensaje, exito):
        """Notificación con el resultado, pegajosa para que se pueda leer."""
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": titulo,
                "message": mensaje,
                "type": "success" if exito else "warning",
                "sticky": True,
            },
        }
