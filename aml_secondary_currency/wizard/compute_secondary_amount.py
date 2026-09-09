from odoo import models, _
from odoo.exceptions import UserError


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def compute_secondary_amount(self):
        """Recalcula la divisa secundaria de los apuntes seleccionados.

        A diferencia del recálculo automático, esta acción la dispara el
        usuario de forma explícita: acá sí conviene avisar con un error si
        falta la moneda secundaria o el tipo de cambio, porque el usuario está
        esperando ver el resultado del cálculo.

        Raises:
            UserError: si la acción no se ejecuta desde Apuntes Contables, si
                no hay apuntes seleccionados, o si falta configuración o
                cotización para calcular el importe.
        """
        if self._context.get('active_model') != 'account.move.line':
            raise UserError(_(
                "Esta operación debe realizarse desde el menú Apuntes Contables"
            ))

        move_lines = self.env['account.move.line'].browse(
            self._context.get('active_ids', [])
        ).exists()
        if not move_lines:
            raise UserError(_("No se encontraron apuntes"))
        move_lines._apply_secondary_currency(strict=True)
