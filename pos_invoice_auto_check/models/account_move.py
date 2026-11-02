# -*- coding: utf-8 -*-
import logging

import psycopg2

from odoo import _, models

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _pos_cfe_estado(self, error=''):
        """Si la factura del PDV quedó registrada sin CFE.

        Con la emisión después del posteo (LocalizacionUy), un fallo de UCFE ya no
        corta la venta: la factura queda registrada y el CFE pendiente. El PDV no
        puede seguir así, porque la rutina impresa necesita el CFE.

        Las de contingencia no cuentan: su CFC se manda después a propósito.
        """
        move = self.sudo()
        pendiente = bool(
            move
            and 'uy_cfe_pendiente' in move._fields and move.uy_cfe_pendiente
            and not ('cfe_contingencia' in move._fields and move.cfe_contingencia))
        return {'pendiente': pendiente, 'error': error if pendiente else '',
                'factura': move.name or ''}

    def _pos_cfe_reintentar(self):
        """El reintento que pide el cajero desde el PDV. No propaga nada."""
        estado = self._pos_cfe_estado()
        if not estado['pendiente']:
            return estado
        move = self.sudo()
        try:
            move.with_company(move.company_id).action_uy_emitir_cfe()
        except Exception as error:  # UCFE caído, rechazo de DGI, dato fiscal faltante
            # La localización commitea antes de mandar a UCFE: la venta no se pierde.
            # Un error de base de datos deja la transacción abortada y hay que
            # descartarla para poder contestar; uno de validación (lo normal) no.
            try:
                self.env.cr.execute('SELECT 1')
            except psycopg2.errors.InFailedSqlTransaction:
                self.env.cr.rollback()
            self.env.invalidate_all()
            motivo = (getattr(error, 'args', None) or [str(error)])[0]
            _logger.warning('pos_invoice_auto_check: reintento de CFE fallido | factura=%s | %s',
                            self.id, motivo)
            return self._pos_cfe_estado(str(motivo or _('Error desconocido al emitir el CFE.')))
        self.env.invalidate_all()
        return self._pos_cfe_estado()
