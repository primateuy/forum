import logging
from odoo.addons.stock.models.stock_rule import ProcurementException
from odoo.addons.stock.models.stock_rule import ProcurementGroup as pg

_logger = logging.getLogger(__name__)
import logging
from collections import defaultdict

from odoo import SUPERUSER_ID, _, api, fields, models, registry
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero, html_escape

_logger = logging.getLogger(__name__)


# class ProcurementException(Exception):
#     """An exception raised by ProcurementGroup `run` containing all the faulty
#     procurements.
#     """
#
#     def __init__(self, procurement_exceptions):
#         """:param procurement_exceptions: a list of tuples containing the faulty
#         procurement and their error messages
#         :type procurement_exceptions: list
#         """
#         self.procurement_exceptions = procurement_exceptions

#@api.model
def run(self, procurements, raise_user_error=True):
    """Fulfil `procurements` with the help of stock rules.

    Procurements are needs of products at a certain location. To fulfil
    these needs, we need to create some sort of documents (`stock.move`
    by default, but extensions of `_run_` methods allow to create every
    type of documents).

    :param procurements: the description of the procurement
    :type list: list of `~odoo.addons.stock.models.stock_rule.ProcurementGroup.Procurement`
    :param raise_user_error: will raise either an UserError or a ProcurementException
    :type raise_user_error: boolan, optional
    :raises UserError: if `raise_user_error` is True and a procurement isn't fulfillable
    :raises ProcurementException: if `raise_user_error` is False and a procurement isn't fulfillable
    """

    def raise_exception(procurement_errors):
        if raise_user_error:
            dummy, errors = zip(*procurement_errors)
            raise UserError('\n'.join(errors))
        else:
            raise ProcurementException(procurement_errors)

    actions_to_run = defaultdict(list)
    procurement_errors = []
    for procurement in procurements:
        procurement.values.setdefault('company_id', procurement.location_id.company_id)
        procurement.values.setdefault('priority', '0')
        procurement.values.setdefault('date_planned', fields.Datetime.now())
        if (
                procurement.product_id.type not in ('consu', 'product') or
                float_is_zero(procurement.product_qty, precision_rounding=procurement.product_uom.rounding)
        ):
            continue
        ########################################################################
        # Added this portion to Manage ICT and IWT creation from the orderpoint.#
        ########################################################################
        orderpoint = procurement and procurement.values and procurement.values.get('orderpoint_id', False) or False
        creation_option = orderpoint and orderpoint.document_creation_option or False
        if self._context.get('custom_order_point_function', False) and creation_option != 'od_default':
            if creation_option:
                if creation_option == 'ict':
                    actions_to_run['ict'].append((procurement))
                elif creation_option == 'iwt':
                    actions_to_run['iwt'].append((procurement))
                elif creation_option == 'po':
                    domain = self.get_po_rule_domain(procurement)
                    # rule = self.env['stock.rule'].search([('action', '=', 'buy'),
                    #                                       ('warehouse_id', '=', procurement.warehouse_id.id)
                    #                                       ('company_id', '=', procurement.company_id.id)], limit=1)
                    rule = self.env['stock.rule'].search(domain, order='route_sequence, sequence', limit=1)
                    if not rule:
                        error = _(
                            'No rule has been found to replenish "%s" in "%s".\nVerify the routes configuration '
                            'on the product.') % \
                                (procurement.product_id.display_name, procurement.location_id.display_name)
                        procurement_errors.append((procurement, error))
                    else:
                        action = rule.action
                        actions_to_run[action].append((procurement, rule))
                continue
        ########################################################################
        rule = self._get_rule(procurement.product_id, procurement.location_id, procurement.values)
        if not rule:
            error = _(
                'No rule has been found to replenish "%s" in "%s".\nVerify the routes configuration on the product.') % \
                    (procurement.product_id.display_name, procurement.location_id.display_name)
            procurement_errors.append((procurement, error))
        else:
            action = 'pull' if rule.action == 'pull_push' else rule.action
            actions_to_run[action].append((procurement, rule))

    if procurement_errors:
        raise_exception(procurement_errors)

    for action, procurements in actions_to_run.items():
        if hasattr(self.env['stock.rule'], '_run_%s' % action):
            try:
                getattr(self.env['stock.rule'], '_run_%s' % action)(procurements)
            except ProcurementException as e:
                procurement_errors += e.procurement_exceptions
        else:
            _logger.error("The method _run_%s doesn't exist on the procurement rules" % action)

    if procurement_errors:
        raise_exception(procurement_errors)
    return True
pg.run = run


class ProcurementGroup(models.Model):
    _inherit = "procurement.group"

    def get_po_rule_domain(self, procurement):
        """
        This method will prepare domain for finding stock rule for po.
        :param procurement: Procurement dict object.
        :return: It will return stock rule domain.
        """
        domain = [('location_dest_id', '=', procurement.location_id.id), ('action', '=', 'buy')]
        warehouse = procurement.values.get('warehouse_id', False)
        if warehouse:
            domain.append(('warehouse_id', '=', warehouse.id))
        return domain

    @api.model
    def run_scheduler(self, use_new_cursor=False, company_id=False):
        context = self._context.copy() or {}
        context.update({'custom_order_point_function': True})
        return super(ProcurementGroup, self.with_context(context)).run_scheduler(use_new_cursor=use_new_cursor,
                                                                                 company_id=company_id)
