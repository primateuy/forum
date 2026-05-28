# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPuntoEmisionCrossCompany(TransactionCase):
    """Verifica que un picking de la company operativa puede portar un punto de
    emisión de otra company (el RUT fiscal de la tienda) sin que
    `_check_company()` levante "Empresas incompatibles"."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_operativa = cls.env.company
        # Company fiscal distinta (simula Faringol SA frente a FORUM)
        cls.company_fiscal = cls.env['res.company'].create({'name': 'Compania Fiscal Test'})
        # Sucursal + punto de emisión que pertenecen a la company FISCAL
        cls.sucursal_fiscal = cls.env['dgi.sucursal'].create({
            'name': 'Sucursal Fiscal Test',
            'company_id': cls.company_fiscal.id,
        })
        cls.punto_fiscal = cls.env['dgi.punto.emision'].create({
            'name': 'Punto Emision Fiscal Test',
            'dgi_sucursal_id': cls.sucursal_fiscal.id,
            'company_id': cls.company_fiscal.id,
        })
        cls.picking_type = cls.env['stock.picking.type'].search(
            [('code', '=', 'internal'), ('company_id', '=', cls.company_operativa.id)],
            limit=1,
        )

    def test_field_check_company_desactivado(self):
        """El override deja `punto_emision_id.check_company = False`."""
        field = self.env['stock.picking']._fields['punto_emision_id']
        self.assertFalse(
            field.check_company,
            "El override del módulo debería dejar check_company=False en punto_emision_id",
        )

    def test_check_company_no_falla_con_punto_de_otra_company(self):
        """Un picking de la company operativa con punto de emisión de la company
        fiscal NO debe romper `_check_company()` (que dispara action_confirm)."""
        self.assertTrue(self.picking_type, "No hay picking type interno en la company operativa")
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'punto_emision_id': self.punto_fiscal.id,
        })
        self.assertEqual(picking.company_id, self.company_operativa)
        self.assertEqual(picking.punto_emision_id.company_id, self.company_fiscal)
        # Sin el fix esto levantaría UserError "Incompatible companies on records".
        try:
            picking._check_company()
        except Exception as exc:  # noqa: BLE001 - el test debe fallar con el mensaje claro
            self.fail(
                "_check_company() no debería fallar con un punto de emisión de otra "
                "company tras el fix; levantó: %s" % exc
            )
