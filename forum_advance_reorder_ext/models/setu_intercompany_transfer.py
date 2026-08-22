# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class SetuIntercompanyTransfer(models.Model):
    _inherit = 'setu.intercompany.transfer'

    def _forum_get_channel(self):
        """Devuelve el canal ICT/IWT del traslado, mirando también el traslado de origen.

        En los traslados de devolución (reverse_transfer) el canal suele estar solo en
        origin_ict_id, no en el registro propio.
        """
        self.ensure_one()
        canal = self.interwarehouse_channel_id or self.intercompany_channel_id
        if not canal and self.origin_ict_id:
            canal = self.origin_ict_id.interwarehouse_channel_id or self.origin_ict_id.intercompany_channel_id
        return canal

    def _forum_channel_picking_type(self, role='fulfiller'):
        """Resuelve el tipo de operación configurado en el canal para un rol dado.

        :param role: 'fulfiller' para el picking del almacén origen, 'requestor' para el
            del almacén destino (segundo paso del traslado en dos pasos).
        :return: recordset de stock.picking.type, vacío si el canal no lo tiene configurado.
        """
        self.ensure_one()
        canal = self._forum_get_channel()
        if not canal:
            return self.env['stock.picking.type']
        if role == 'requestor':
            return canal.requestor_picking_type_id
        return canal.picking_type_id

    def create_direct_picking(self):
        """Usa el tipo de operación del canal para el traslado directo, si está configurado.

        Sin configuración se delega íntegramente al super(), así el comportamiento por
        defecto de Setu queda intacto.
        """
        picking_type = self._forum_channel_picking_type('fulfiller') or \
            self._forum_channel_picking_type('requestor')
        if not picking_type:
            return super().create_direct_picking()

        destination = self.find_source_dest_location()
        picking_vals = self.prepare_picking_vals(
            dest_location_id=destination and destination.id or False,
            picking_type_id=picking_type.id,
        )
        picking_vals.update({
            'move_ids_without_package': self.prepare_move_vals(picking_type_id=picking_type.id),
        })
        picking = self.env['stock.picking'].create(picking_vals)
        picking.with_company(self.fulfiller_company_id).action_confirm()
        picking.with_company(self.fulfiller_company_id).action_assign()
        return picking

    def create_two_step_pickings(self):
        """Usa los tipos de operación del canal en el traslado en dos pasos.

        Además corrige un descuido del módulo base: Setu calcula el picking_type_id del
        primer picking pero solo se lo pasa a prepare_move_vals, no a prepare_picking_vals,
        con lo cual el picking tomaba el fallback (int_type_id del almacén). Hoy coincidían
        en valor; al poder configurarlos dejarían de coincidir.
        """
        tipo_origen = self._forum_channel_picking_type('fulfiller')
        tipo_destino = self._forum_channel_picking_type('requestor')
        if not tipo_origen and not tipo_destino:
            return super().create_two_step_pickings()

        transit_location = self.get_trasit_location()
        dest_location_id = self.find_source_dest_location()
        src_location_id = self.fulfiller_warehouse_id.lot_stock_id.id
        dest_location_id = dest_location_id.id

        picking_type_id = tipo_origen.id or self.fulfiller_warehouse_id.int_type_id.id
        partner_id = self.requestor_warehouse_id.partner_id.id

        # Primer picking: origen → tránsito.
        picking_vals = self.prepare_picking_vals(
            src_location_id=src_location_id,
            dest_location_id=transit_location,
            warehouse=self.fulfiller_warehouse_id,
            picking_type_id=picking_type_id,
        )
        picking_vals.update({
            'move_ids_without_package': self.prepare_move_vals(
                src_location_id=src_location_id,
                dest_location_id=transit_location,
                warehouse=self.fulfiller_warehouse_id,
                partner_id=partner_id,
                picking_type_id=picking_type_id,
            ),
        })
        first_picking = self.env['stock.picking'].create(picking_vals)
        first_picking.with_company(self.fulfiller_company_id).action_confirm()
        first_picking.with_company(self.fulfiller_company_id).action_assign()

        # Segundo picking: tránsito → destino.
        picking_type_id = tipo_destino.id or self.requestor_warehouse_id.int_type_id.id
        partner_id = self.requestor_warehouse_id.partner_id.id
        picking_vals = self.prepare_picking_vals(
            src_location_id=transit_location,
            dest_location_id=dest_location_id,
            warehouse=self.requestor_warehouse_id,
            partner_id=partner_id,
            picking_type_id=picking_type_id,
        )
        second_picking = self.env['stock.picking'].create(picking_vals)
        for move in first_picking.move_ids_without_package:
            move.copy({
                'name': move.name,
                'location_id': transit_location,
                'location_dest_id': dest_location_id,
                'picking_type_id': picking_type_id,
                'move_orig_ids': [(6, 0, [move.id])],
                'picking_id': second_picking.id,
                'state': 'waiting',
            })
        return True

    def create_two_step_reverse_pickings(self):
        """Ídem create_two_step_pickings, con los roles invertidos por ser una devolución."""
        tipo_origen = self._forum_channel_picking_type('fulfiller')
        tipo_destino = self._forum_channel_picking_type('requestor')
        if not tipo_origen and not tipo_destino:
            return super().create_two_step_reverse_pickings()

        transit_location = self.get_trasit_location()
        dest_location_id = self.fulfiller_warehouse_id.lot_stock_id.id
        src_location_id = self.requestor_warehouse_id.lot_stock_id.id

        # En la devolución la salida es del almacén destino original (requestor).
        picking_type_id = tipo_destino.id or self.requestor_warehouse_id.int_type_id.id
        partner_id = self.fulfiller_warehouse_id.partner_id.id

        picking_vals = self.prepare_picking_vals(
            src_location_id=src_location_id,
            dest_location_id=transit_location,
            warehouse=self.requestor_warehouse_id,
            partner_id=partner_id,
            picking_type_id=picking_type_id,
        )
        picking_vals.update({
            'move_ids_without_package': self.prepare_move_vals(
                src_location_id=src_location_id,
                dest_location_id=transit_location,
                warehouse=self.requestor_warehouse_id,
                partner_id=partner_id,
                picking_type_id=picking_type_id,
            ),
        })
        first_picking = self.env['stock.picking'].create(picking_vals)
        first_picking.with_company(self.fulfiller_company_id).action_confirm()
        first_picking.with_company(self.fulfiller_company_id).action_assign()

        # La entrada es en el almacén origen original (fulfiller).
        picking_type_id = tipo_origen.id or self.fulfiller_warehouse_id.int_type_id.id
        partner_id = self.fulfiller_warehouse_id.partner_id.id
        picking_vals = self.prepare_picking_vals(
            src_location_id=transit_location,
            dest_location_id=dest_location_id,
            warehouse=self.fulfiller_warehouse_id,
            partner_id=partner_id,
            picking_type_id=picking_type_id,
        )
        second_picking = self.env['stock.picking'].create(picking_vals)
        for move in first_picking.move_ids_without_package:
            move.copy({
                'name': move.name,
                'location_id': transit_location,
                'location_dest_id': dest_location_id,
                'picking_type_id': picking_type_id,
                'move_orig_ids': [(6, 0, [move.id])],
                'picking_id': second_picking.id,
                'state': 'waiting',
            })
        return True
