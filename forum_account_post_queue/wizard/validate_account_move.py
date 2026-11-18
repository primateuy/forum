import logging

from odoo import _, models
from odoo.exceptions import UserError

from ..models.account_move import DEFAULT_MIN_FACTURAS, PARAM_MIN_FACTURAS

_logger = logging.getLogger(__name__)


class ValidateAccountMove(models.TransientModel):
    _inherit = "validate.account.move"

    def _forum_moves_a_registrar(self):
        """Mismo conjunto que arma el asistente del core antes de registrar."""
        if self._context.get("active_model") == "account.move":
            dominio = [
                ("id", "in", self._context.get("active_ids", [])),
                ("state", "=", "draft"),
            ]
        elif self._context.get("active_model") == "account.journal":
            dominio = [
                ("journal_id", "=", self._context.get("active_id")),
                ("state", "=", "draft"),
            ]
        else:
            raise UserError(_("Falta 'active_model' en el contexto."))
        return self.env["account.move"].search(dominio).filtered("line_ids")

    def validate_move(self):
        """Registrar muchas facturas juntas las manda a la cola, no las postea.

        Registrar en lote revienta con un RecursionError del core cuando la
        tanda junta demasiadas lineas, y aun sin el error tardaria minutos con
        el navegador colgado. Asi que a partir de cierta cantidad de facturas se
        encolan y las registra el cron de a tandas.

        Por debajo de ese minimo se registra en el momento, como siempre: es el
        caso de quien quiere ver una factura publicarse ahora mismo.
        """
        self.ensure_one()
        AccountMove = self.env["account.move"]
        minimo = AccountMove._forum_queue_param(PARAM_MIN_FACTURAS, DEFAULT_MIN_FACTURAS)

        moves = self._forum_moves_a_registrar()
        if len(moves) < minimo:
            return super().validate_move()

        if self.force_post:
            # Mismo motivo que en `_forum_write_cola`: escribir sobre un lote
            # grande de borradores recalcularia las lineas dinamicas de cada
            # factura y volveria a dar el RecursionError que se quiere evitar.
            moves._forum_write_cola({"auto_post": "no"})
        encoladas = moves._forum_enqueue_post(force_post=self.force_post)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": _("Facturas en cola"),
                "message": _(
                    "%s facturas quedaron en cola. Se van a registrar solas en "
                    "los proximos minutos; no hace falta esperar en esta "
                    "pantalla. Si necesitas una ya, abrila y usa Confirmar.",
                    len(encoladas),
                ),
                "sticky": True,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
