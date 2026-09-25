# -*- coding: utf-8 -*-

from odoo import _, models


class PosSession(models.Model):
    """
    No se cierra la caja con emisiones de CFE pendientes.

    Una venta con la factura en borrador no se puede conciliar al cerrar la
    sesión —el core reconcilia contra los apuntes de la factura, y los de un
    asiento en borrador no se pueden conciliar—, así que el cierre reventaría
    con un error de contabilidad. Se bloquea antes, con un mensaje que dice qué
    venta hay que resolver.
    """

    _inherit = "pos.session"

    def _cannot_close_session(self, bank_payment_method_diffs=None):
        # Bloque: el core documenta este método como el punto de extensión para
        # impedir el cierre. Devolver el dict evita el traceback y muestra el
        # mensaje en el PDV.
        pendientes = self.order_ids.filtered("cfe_emision_pendiente")
        if pendientes:
            referencias = ", ".join(
                p.pos_reference or p.name for p in pendientes[:5]
            )
            if len(pendientes) > 5:
                referencias += ", …"
            return {
                "successful": False,
                "message": _(
                    "No se puede cerrar la caja: hay %(cantidad)s venta(s) con el CFE sin emitir "
                    "(%(refs)s). Resolvé la emisión desde el PDV o desde la factura en borrador "
                    "antes de cerrar.",
                    cantidad=len(pendientes),
                    refs=referencias,
                ),
                "redirect": False,
            }
        return super()._cannot_close_session(bank_payment_method_diffs=bank_payment_method_diffs)
