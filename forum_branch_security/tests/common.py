# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase


class BranchProfileCase(TransactionCase):
    """Un local de franquicia: PDV en una compañía, almacén en otra."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.casa_central = cls.env['res.company'].create({'name': 'Casa Central BP'})
        cls.franquicia = cls.env['res.company'].create({
            'name': 'Franquicia BP', 'parent_id': cls.casa_central.id,
        })
        cls.warehouse = cls.env['stock.warehouse'].create({
            'name': 'Local BP', 'code': 'LBP',
            'company_id': cls.casa_central.id, 'is_branch': True,
        })
        cls.otro_warehouse = cls.env['stock.warehouse'].create({
            'name': 'Otro Local BP', 'code': 'OBP',
            'company_id': cls.casa_central.id, 'is_branch': True,
        })
        # Un pos.config en una compania nueva hereda diarios y metodos de pago de
        # otra compania y _check_company los rechaza. Se le crean los propios.
        cls.journal_pos = cls.env['account.journal'].create({
            'name': 'PDV Test', 'type': 'general', 'code': 'PDVT',
            'company_id': cls.franquicia.id,
        })
        cls.journal_venta = cls.env['account.journal'].create({
            'name': 'Ventas Test', 'type': 'sale', 'code': 'VTAT',
            'company_id': cls.franquicia.id,
        })
        cls.pos_config = cls.env['pos.config'].create({
            'name': 'PDV Local BP', 'company_id': cls.franquicia.id,
            'payment_method_ids': [(5, 0, 0)],
            'journal_id': cls.journal_pos.id,
            'invoice_journal_id': cls.journal_venta.id,
        })
        cls.otro_pos = cls.env['pos.config'].create({
            'name': 'PDV Otro Local BP', 'company_id': cls.franquicia.id,
            'payment_method_ids': [(5, 0, 0)],
            'journal_id': cls.journal_pos.id,
            'invoice_journal_id': cls.journal_venta.id,
        })
        cls.warehouse.branch_pos_config_ids = cls.pos_config
        cls.otro_warehouse.branch_pos_config_ids = cls.otro_pos

        cls.branch_group = cls.env.ref('forum_branch_security.group_branch_user')
        cls.cost_group = cls.env.ref('forum_branch_security.group_product_cost')

        cls.user = cls.env['res.users'].create({
            'name': 'Cajero BP', 'login': 'cajero.bp',
            'company_id': cls.franquicia.id,
            'company_ids': [(6, 0, [cls.franquicia.id])],
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.branch_group.id,
            ])],
        })
        cls.user.branch_warehouse_ids = cls.warehouse

        cls.supervisor = cls.env['res.users'].create({
            'name': 'Supervisor BP', 'login': 'supervisor.bp',
            'company_id': cls.casa_central.id,
            'company_ids': [(6, 0, [cls.casa_central.id])],
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('forum_branch_security.group_branch_supervisor').id,
            ])],
        })
        cls.supervisor.branch_warehouse_ids = cls.warehouse | cls.otro_warehouse

    def as_branch_user(self, model):
        return self.env[model].with_user(self.user)
