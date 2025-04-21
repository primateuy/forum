import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class IrSequence(models.Model):
    _inherit = 'ir.sequence'

    @api.model
    def next_by_code(self, sequence_code, sequence_date=None):
        sequence_number = super(IrSequence, self).next_by_code(sequence_code, sequence_date)
        if not sequence_number:
            allowed_company_ids = self._context.get('allowed_company_ids')
            seq_ids = self.search([('code', '=', sequence_code), ('company_id', 'in', allowed_company_ids)])
            if not seq_ids:
                _logger.debug(
                    "No ir.sequence has been found for code '%s'. Please make sure a sequence is set for current company." % sequence_code)
                return False
            seq_id = seq_ids[0]
            return seq_id._next(sequence_date=sequence_date)
        else:
            return sequence_number
