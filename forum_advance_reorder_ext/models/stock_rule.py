# -*- coding: utf-8 -*-
import logging

from odoo import models
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class StockRule(models.Model):
    _inherit = 'stock.rule'

    def create_iwt_lines(self, channel, procurements, place='iwt'):
        """Redondea la cantidad de la transferencia inter-depósito al múltiplo del producto.

        Reimplementación completa del método de Setu (setu_advance_reordering 17.0.0.2,
        stock_rule.py:369). No alcanza con un post-hook porque la cantidad enviada y el
        remanente que pasa al siguiente canal de la cadena se calculan juntos.

        Criterio:
        - Productos sin múltiplo (> 1): comportamiento original, byte por byte. Si ningún
          producto del lote tiene múltiplo, se delega directo al super().
        - Productos con múltiplo: la cantidad se redondea hacia arriba al múltiplo, salvo
          que supere el stock disponible en origen, caso en el que baja al múltiplo
          inferior (floor de rescate). Así la IWT nunca nace con una cantidad que
          stock_multiplos_validation vaya a rechazar en action_assign.
        - Si el remanente que queda pendiente es menor al múltiplo, se descarta: cubrirlo
          desde otro origen obligaría a mandar un pack entero de más.
        """
        product_obj = self.env['product.product']
        productos_lote = product_obj.browse([pid for pid in procurements.keys()])
        if not any((p.mutiplos_distribucion or 1) > 1 for p in productos_lote):
            return super().create_iwt_lines(channel, procurements, place=place)

        ict_iwt_lines = []
        warehouse = channel.requestor_warehouse_id
        fulfiller_warehouse = channel.fulfiller_warehouse_id
        iwt_obj = self.env['setu.intercompany.transfer']
        product_dict = procurements.copy()

        for product, qty in product_dict.items():
            product_obj_rec = product_obj.browse(product)
            remaining_qty = procurements.get(product, 0)
            if not remaining_qty:
                continue

            wh_available_stock = product_obj_rec.with_context({'warehouse': fulfiller_warehouse.id}).qty_available
            wh_outgoing_stock = product_obj_rec.with_context({'warehouse': fulfiller_warehouse.id}).outgoing_qty
            net_on_hand = wh_available_stock - wh_outgoing_stock
            if net_on_hand <= 0.0:
                net_on_hand = 0.0
            if not net_on_hand:
                continue

            order_qty = min(remaining_qty, net_on_hand)
            multiple = product_obj_rec.mutiplos_distribucion or 1
            rounding = product_obj_rec.uom_id.rounding or 0.01

            if multiple > 1:
                order_qty = product_obj_rec.forum_round_to_distribution_multiple(
                    order_qty, max_qty=net_on_hand
                )
                if order_qty <= 0:
                    # No entra ni un múltiplo en el stock de origen: queda todo pendiente
                    # para el siguiente canal de la cadena.
                    _logger.info(
                        "IWT %s: %s tiene múltiplo %s y solo %s disponibles en %s, se omite.",
                        channel.display_name, product_obj_rec.display_name, multiple,
                        net_on_hand, fulfiller_warehouse.display_name,
                    )
                    continue
                pendiente = remaining_qty - order_qty
                if float_compare(pendiente, multiple, precision_rounding=rounding) >= 0:
                    procurements.update({product_obj_rec.id: pendiente})
                else:
                    procurements.pop(product_obj_rec.id, None)
            else:
                # Comportamiento original de Setu, sin tocar.
                if net_on_hand < remaining_qty:
                    procurements.update({product_obj_rec.id: remaining_qty - order_qty})
                else:
                    procurements.pop(product_obj_rec.id, None)

            iwt_domain = self.iwt_search_domain(warehouse, channel)
            existing_ict_iwt = iwt_obj.search(iwt_domain)
            ict_iwt_line_exists = existing_ict_iwt.intercompany_transfer_line_ids.filtered(
                lambda x: x.product_id == product_obj_rec
            )
            if ict_iwt_line_exists:
                ict_iwt_line_exists[0].write({'quantity': order_qty})
            else:
                ict_iwt_lines.append((0, 0, {
                    'product_id': product,
                    'quantity': order_qty,
                    'unit_price': 0,
                }))

        return ict_iwt_lines, procurements
