# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError


class CreateReordering(models.TransientModel):
    _inherit = 'create.reordering'

    def action_add_products_from_categories(self):
        """Carga en product_ids los productos de las categorías elegidas y de sus hijas.

        El campo product_category_ids ya venía declarado en el wizard de Setu pero sin
        efecto sobre product_ids (solo se usaba para filtrar el histórico de ventas). Con
        esto el mismo criterio de selección masiva del proceso de Reorder queda disponible
        acá, y como todo termina en product_ids, create_reorder_rule y
        prepare_orderpoint_domain lo recogen sin cambios.

        Se filtra por productos almacenables, que son los únicos para los que Setu genera
        reglas de reabastecimiento.
        """
        self.ensure_one()
        if not self.product_category_ids:
            raise UserError(_('Elegí al menos una categoría de producto.'))

        candidatos = self.env['product.product'].forum_products_from_categories(
            self.product_category_ids,
            extra_domain=[('type', '=', 'product')],
        )
        nuevos = candidatos - self.product_ids
        if nuevos:
            self.product_ids = [(4, product.id) for product in nuevos]

        # El wizard es un formulario modal: se reabre para que el usuario vea el resultado
        # y siga configurando la operación.
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'create.reordering',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'views': [(self.env.ref('setu_advance_reordering.form_create_reordering').id, 'form')],
        }
