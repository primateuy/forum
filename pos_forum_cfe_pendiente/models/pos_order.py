# -*- coding: utf-8 -*-

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    """
    Venta del PDV con la emisión del CFE desacoplada del guardado.

    El flujo de siempre hacía todo en una transacción: orden + factura +
    emisión. Si el CFE fallaba, revertía todo y la venta no quedaba en ningún
    lado, aunque el cobro ya se hubiera hecho. Acá la emisión deja de ser la que
    aborta: si falla, la venta queda guardada, la factura en borrador y la orden
    marcada como pendiente de emisión.
    """

    _inherit = "pos.order"

    cfe_emision_pendiente = fields.Boolean(
        string="Emisión de CFE pendiente",
        copy=False,
        index=True,
        help="La venta se guardó pero el CFE no se pudo emitir. La factura está "
             "en borrador y la caja no se puede cerrar hasta resolverlo.",
    )
    cfe_emision_error = fields.Text(
        string="Motivo del fallo de emisión",
        copy=False,
        help="Último error devuelto al intentar emitir el CFE.",
    )
    cfe_emision_intentos = fields.Integer(
        string="Intentos de emisión",
        copy=False,
        default=0,
    )
    cfe_emision_ultimo_intento = fields.Datetime(
        string="Último intento de emisión",
        copy=False,
    )

    # ------------------------------------------------------------------
    # Creación de la factura
    # ------------------------------------------------------------------

    # Errores de los que se puede seguir: dejan la transacción usable, así que
    # todavía se puede marcar la orden. Un error de base de datos la deja
    # abortada y no hay nada que escribir: ése se relanza.
    _CFE_ERRORES_RECUPERABLES = (UserError, ValidationError)

    def _generate_pos_order_invoice(self):
        """
        Intenta el flujo normal; si la emisión falla, deja la factura en borrador.

        🔴 Sin savepoint, a propósito. La localización hace
        ``self._cr.commit()`` antes de mandarle el CFE a Uruware
        (l10n_uy_einvoice_uruware/models/account_move.py:2722), así que cualquier
        savepoint abierto acá ya no existe cuando habría que volver atrás:
        intentar el ROLLBACK TO SAVEPOINT tira ``savepoint does not exist`` y
        deja la transacción abortada, que es peor que el problema original.

        Ese commit también explica por qué hoy, cuando falla la emisión DESPUÉS
        de mandar, la venta igual queda guardada: ya está commiteada. Lo que
        falta es que el PDV se entere, y de eso se encarga el resto del módulo.

        La factura ya está creada y enlazada cuando se llega a postear, así que
        no hay que rehacer nada: alcanza con no postearla y marcar la orden.
        """
        pendientes = self.env["pos.order"]
        resultado = {}
        for order in self:
            try:
                resultado = super(PosOrder, order)._generate_pos_order_invoice()
            except self._CFE_ERRORES_RECUPERABLES as error:
                _logger.warning(
                    "pos_forum_cfe_pendiente: no se pudo emitir el CFE de la venta %s; "
                    "queda con la factura en borrador. Motivo: %s",
                    order.pos_reference or order.name, error,
                )
                order._cfe_crear_factura_en_borrador(error)
                pendientes |= order

        if pendientes:
            # Sin factura posteada no hay acción de factura que devolver; el PDV
            # se entera por el flag que viaja en create_from_ui.
            return {}
        return resultado

    def _cfe_crear_factura_en_borrador(self, error):
        """
        Rehace la factura sin postearla y deja la orden marcada como pendiente.

        :param error: excepción que devolvió el intento de emisión.
        """
        self.ensure_one()
        if not self.account_move:
            move_vals = self._prepare_invoice_vals()
            nueva = self._create_invoice(move_vals)
            self.write({"account_move": nueva.id, "state": "invoiced"})
        self.write({
            "cfe_emision_pendiente": True,
            "cfe_emision_error": self._cfe_texto_error(error),
            "cfe_emision_intentos": (self.cfe_emision_intentos or 0) + 1,
            "cfe_emision_ultimo_intento": fields.Datetime.now(),
        })

    @api.model
    def _cfe_texto_error(self, error):
        """Mensaje legible para el cajero, sin traceback."""
        texto = getattr(error, "name", None) or str(error) or _("Error desconocido al emitir el CFE.")
        return texto.strip()

    # ------------------------------------------------------------------
    # Reintento
    # ------------------------------------------------------------------

    @api.model
    def reintentar_emision_cfe(self, order_id):
        """
        Reintenta la emisión de la factura en borrador de una venta.

        No rehace nada: postea el mismo ``account.move`` que quedó en borrador.
        Se usa ``action_post`` y no ``_post`` para pasar por todos los overrides
        de la localización.

        Si el CFE ya se había emitido en UCFE y lo que falló fue el posteo
        posterior, la localización no lo vuelve a emitir: lo marca con
        ``cfe_emitido`` y sólo termina de postear.

        :param int order_id: id de ``pos.order``.
        :return dict: ``{'ok': bool, 'error': str, 'intentos': int}``
        """
        order = self.browse(order_id)
        if not order.exists():
            return {"ok": False, "error": _("No se encontró la venta."), "intentos": 0}
        move = order.account_move
        if not move:
            return {"ok": False, "error": _("La venta no tiene factura asociada."),
                    "intentos": order.cfe_emision_intentos}
        if move.state == "posted":
            order._cfe_marcar_resuelto()
            return {"ok": True, "error": "", "intentos": order.cfe_emision_intentos}

        try:
            move.action_post()
        except self._CFE_ERRORES_RECUPERABLES as error:
            # Mismo motivo que arriba: nada de savepoints. Estos errores dejan la
            # transacción usable, así que todavía se puede guardar el motivo.
            order.write({
                "cfe_emision_error": self._cfe_texto_error(error),
                "cfe_emision_intentos": (order.cfe_emision_intentos or 0) + 1,
                "cfe_emision_ultimo_intento": fields.Datetime.now(),
            })
            _logger.warning(
                "pos_forum_cfe_pendiente: reintento fallido de emisión | venta=%s | motivo=%s",
                order.pos_reference or order.name, error,
            )
            return {"ok": False, "error": order.cfe_emision_error,
                    "intentos": order.cfe_emision_intentos}

        order._cfe_marcar_resuelto()
        _logger.info(
            "pos_forum_cfe_pendiente: emisión resuelta en el reintento | venta=%s | factura=%s",
            order.pos_reference or order.name, move.name,
        )
        return {"ok": True, "error": "", "intentos": order.cfe_emision_intentos}

    def _cfe_marcar_resuelto(self):
        self.write({
            "cfe_emision_pendiente": False,
            "cfe_emision_error": False,
        })

    # ------------------------------------------------------------------
    # Lo que ve el PDV
    # ------------------------------------------------------------------

    @api.model
    def create_from_ui(self, orders, draft=False):
        """
        Agrega el estado de emisión a lo que el PDV recibe al guardar la venta.

        El core devuelve sólo ``id``, ``pos_reference`` y ``account_move``; el
        PDV necesita saber si la venta quedó con la emisión pendiente para
        mostrar la pantalla de reintento en vez de avanzar al recibo.
        """
        return self._cfe_agregar_estado_emision(super().create_from_ui(orders, draft=draft))

    @api.model
    def _cfe_agregar_estado_emision(self, res):
        """
        Agrega ``cfe_emision_pendiente`` y ``cfe_emision_error`` a cada fila.

        :param list res: lo que devuelve ``create_from_ui`` (dicts con ``id``).
        :return list: la misma lista, con el estado de emisión de cada venta.
        """
        if not res:
            return res
        datos = {
            d["id"]: d
            for d in self.browse([r["id"] for r in res]).read(
                ["cfe_emision_pendiente", "cfe_emision_error"]
            )
        }
        for fila in res:
            extra = datos.get(fila.get("id")) or {}
            fila["cfe_emision_pendiente"] = extra.get("cfe_emision_pendiente", False)
            fila["cfe_emision_error"] = extra.get("cfe_emision_error") or ""
        return res
