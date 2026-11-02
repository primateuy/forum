# -*- coding: utf-8 -*-
"""Reintento manual del CFE desde el PDV (Forum, 02-11-2026).

Con la emisión después del posteo, un fallo de UCFE deja la factura registrada y el
CFE pendiente. El PDV pregunta el estado después de guardar la venta y, si quedó
pendiente, el cajero reintenta ahí mismo: la rutina impresa necesita el CFE.
"""
import unittest
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCfeReintentoPdv(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'uy_cfe_pendiente' not in cls.env['account.move']._fields:
            raise unittest.SkipTest('Sin la emisión después del posteo de LocalizacionUy')
        cls.env.company.sudo().fe_activa = True
        cls.journal = cls.env['account.journal'].search([
            ('type', '=', 'sale'), ('company_id', '=', cls.env.company.id)], limit=1)
        if not cls.journal:
            raise unittest.SkipTest('No hay diario de ventas en la compañía')
        cls.journal.sudo().diario_cfe = True
        cls.partner = cls.env['res.partner'].create({'name': 'Consumidor reintento CFE'})

    def _factura_pendiente(self):
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice', 'journal_id': self.journal.id,
            'partner_id': self.partner.id,
            'invoice_date': fields.Date.context_today(self.env.user),
            'invoice_line_ids': [(0, 0, {'name': 'Prenda', 'quantity': 1, 'price_unit': 100.0,
                                         'tax_ids': [(5, 0, 0)]})],
        })
        if invoice.journal_id.l10n_latam_use_documents and not invoice.l10n_latam_document_type_id:
            disponibles = invoice.l10n_latam_available_document_type_ids
            if not disponibles:
                self.skipTest('El diario no tiene tipos de documento latam')
            invoice.l10n_latam_document_type_id = disponibles[0]
        # Registrada sin emitir: como queda cuando UCFE no contestó.
        invoice.with_context(dont_send_to_dgi=True).action_post()
        self.assertTrue(invoice.uy_cfe_pendiente)
        return invoice

    def _parche(self, funcion):
        return patch.object(type(self.env['account.move']), 'action_uy_emitir_cfe', funcion)

    def test_01_el_pdv_ve_que_quedo_pendiente(self):
        estado = self._factura_pendiente()._pos_cfe_estado()
        self.assertTrue(estado['pendiente'])

    def test_02_reintento_fallido_devuelve_el_motivo(self):
        invoice = self._factura_pendiente()

        def _caido(move_self):
            raise ValidationError('503, UCFE no responde')

        with self._parche(_caido):
            estado = invoice._pos_cfe_reintentar()
        self.assertTrue(estado['pendiente'])
        self.assertIn('UCFE no responde', estado['error'])

    def test_03_reintento_que_sale_libera_al_pdv(self):
        invoice = self._factura_pendiente()

        def _emite(move_self):
            move_self.cfe_emitido = True
            return True

        with self._parche(_emite):
            estado = invoice._pos_cfe_reintentar()
        self.assertFalse(estado['pendiente'])
        self.assertFalse(estado['error'])

    def test_04_emitido_no_reintenta(self):
        invoice = self._factura_pendiente()
        invoice.cfe_emitido = True
        llamadas = []
        with self._parche(lambda s: llamadas.append(s.ids)):
            estado = invoice._pos_cfe_reintentar()
        self.assertFalse(llamadas)
        self.assertFalse(estado['pendiente'])

    def test_05_contingencia_no_traba_al_pdv(self):
        """La CFC se manda después a propósito: el PDV de contingencia sigue."""
        invoice = self._factura_pendiente()
        if 'cfe_contingencia' not in invoice._fields:
            self.skipTest('Sin l10n_uy_cfc_efac')
        invoice.cfe_contingencia = True
        self.assertFalse(invoice._pos_cfe_estado()['pendiente'])

    def test_06_venta_sin_factura(self):
        self.assertFalse(self.env['account.move']._pos_cfe_estado()['pendiente'])
