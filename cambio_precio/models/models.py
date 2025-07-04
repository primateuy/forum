from odoo import models, fields, api
from odoo.exceptions import ValidationError

import logging
_logger = logging.getLogger(__name__)

class LoyaltyReward(models.Model):
    _inherit = 'loyalty.reward'

    reward_type = fields.Selection(
    selection_add=[('pricelist_change', 'Cambio de Lista de Precios')],
    ondelete={'pricelist_change': 'cascade'}
)
    pricelist_id = fields.Many2one('product.pricelist', string='Lista de Precios (Recompensa)', store=True, help='Lista de precios que se aplicará al cambiar la recompensa')

    description = fields.Text(
    string='Descripción',
    compute='_compute_description',
    store=True,
    help='Descripción de la recompensa, se mostrará en el Punto de Venta'
    )


    @classmethod
    def _pos_ui_export_fields(cls):
        return super()._pos_ui_export_fields() + ['pricelist_id']

  

    @api.model
    def create(self, vals):
        _logger.info("Creando recompensa con valores: %s", vals)
        if vals.get('reward_type') == 'pricelist_change' and not vals.get('pricelist_id'):
            raise ValidationError("Debe seleccionar una lista de precios para el cambio.")



        result = super(LoyaltyReward, self).create(vals)
        _logger.info("Recompensa creada: %s", result)

        return result;
            

    def _create_reward(self, vals):
        if vals.get('reward_type') == 'pricelist_change' and not vals.get('pricelist_id'):
            raise ValidationError("Debe seleccionar una lista de precios para el cambio.")
        return super(LoyaltyReward, self).create(vals)

    @api.depends('reward_type', 'pricelist_id', 'reward_product_ids', 'discount', 'discount_mode')
    def _compute_description(self):

        
        for reward in self:
            _logger.info("Computando descripción para recompensa: %s", reward)
        
            if reward.reward_type == 'pricelist_change':
                _logger.info("VIENDO LA PRICELIST_id %s", reward.pricelist_id.id);

            if reward.reward_type == 'discount':
                if reward.discount_mode == 'percent':
                    reward.description = f"{reward.discount}% de descuento"
                elif reward.discount_mode == 'per_order':
                    reward.description = f"${reward.discount} de descuento"
                else:
                    reward.description = "Recompensa de descuento"

            elif reward.reward_type == 'product':  # Cambié 'gift' por 'product'
                if reward.reward_product_ids:
                    if len(reward.reward_product_ids) == 1:
                        product_name = reward.reward_product_ids[0].display_name
                        if reward.reward_product_qty > 1:
                            
                            reward.description = f"{int(reward.reward_product_qty)}x {product_name} GRATIS"
                        else:
                            reward.description = f"{product_name} GRATIS"
                    else:
                        reward.description = f"{len(reward.reward_product_ids)} productos GRATIS"
                else:
                    reward.description = "Producto gratuito"
            
            elif reward.reward_type == 'pricelist_change':  # CAMBIÉ 'if' por 'elif'
                if reward.pricelist_id:
                    reward.description = f"Cambio a lista: {reward.pricelist_id.display_name}"
                else:
                    reward.description = "Cambio de lista de precios"

            else: 
                reward.description = "Recompensa de lealtad"

    @api.onchange('reward_type')
    def _onchange_reward_type(self):
        if self.reward_type != 'pricelist_change':
            self.pricelist_id = False

    @api.onchange('pricelist_id')
    def _onchange_pricelist_id(self):

        if self.reward_type == 'pricelist_change' and not self.pricelist_id:
            raise ValidationError("Debe seleccionar una lista de precios para el cambio.");

        if self.reward_type == 'pricelist_change' and self.pricelist_id:
            _logger.info("Cambiando lista de precios a: %s", self.pricelist_id.name)
            self.discount_max_amount = self.pricelist_id.id


    def _prepare_reward_line_vals(self, order):
        vals = super()._prepare_reward_line_vals(order)
        if self.reward_type == 'pricelist_change':
            vals.update({
                'name': f"Precios especiales ({self.pricelist_id.name})",
                'price_unit': 0.0,
                'product_id': self.env.ref('point_of_sale.product_product_consumable').id,
                'is_reward_line': True,
            })
        return vals
            
    
class PromoEngine(models.AbstractModel):
    _name = 'promo.engine'
    _description = 'Promo Rule Engine'

    def apply_promotions(self, order):
        rewards = []
        active_programs = self.env['loyalty.program'].search([('active', '=', True)])
        
        _logger.info("Aplicando promociones para el pedido: %s", order);

        for program in active_programs:
            # Verificar condiciones del programa primero
            program_conditions_met = True
            for rule in program.rule_ids:
                if rule.minimum_qty and sum(line.product_uom_qty for line in order.order_line) < rule.minimum_qty:
                    program_conditions_met = False
                    break
                if rule.minimum_amount and order.amount_total < rule.minimum_amount:
                    program_conditions_met = False
                    break
            
            if program_conditions_met:
                for reward in program.reward_ids:
                    if reward.reward_type == 'pricelist_change' and reward.pricelist_id:
                        rewards.append({
                            'type': 'pricelist_change',
                            'pricelist': reward.pricelist_id,
                            'reward_id': reward.id,
                        })
        return rewards

    def _conditions_met(self, order, reward):
        """
        Verifica si se cumplen las condiciones para aplicar la recompensa
        """
        program = reward.program_id
        
        # Verificar reglas del programa
        if program.rule_ids:
            for rule in program.rule_ids:
                # Verificar cantidad mínima
                if rule.minimum_qty and sum(line.product_uom_qty for line in order.order_line) < rule.minimum_qty:
                    return False
                # Verificar monto mínimo
                if rule.minimum_amount and order.amount_total < rule.minimum_amount:
                    return False
        return True


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.onchange('order_line')
    def _onchange_order_line_apply_promo(self):
        engine = self.env['promo.engine']
        rewards = engine.apply_promotions(self)
        for reward in rewards:
            if reward['type'] == 'pricelist_change':
                self.pricelist_id = reward['pricelist'].id


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _apply_reward_pricelist(self, reward, order):
        """
        Aplica cambio de lista de precios en backend para POS
        """
        if reward.pricelist_id:
            order.write({'pricelist_id': reward.pricelist_id.id})
            return True
        return False

    @api.model
    def _process_order(self, order, draft, existing_order):
        order_id = super(PosOrder, self)._process_order(order, draft, existing_order)
        pos_order = self.browse(order_id)
        
        # ✅ BUSCAR DIRECTAMENTE LAS RECOMPENSAS DE PRICELIST_CHANGE
        pricelist_rewards = self.env['loyalty.reward'].search([
            ('reward_type', '=', 'pricelist_change'),
            ('pricelist_id', '!=', False)
        ])

        for reward in pricelist_rewards:
            # Verificar si el reward es aplicable a esta orden
            if reward.program_id.active:
                self._apply_reward_pricelist(reward, pos_order)