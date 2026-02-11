from odoo import models, fields, api
from odoo.exceptions import ValidationError

import logging
_logger = logging.getLogger(__name__)

class PosSession(models.Model):
    _inherit = 'pos.session'

    
    
    # NUEVO: Cargar información de recompensas con sus productos
    def _loader_params_loyalty_reward(self):
        """Extender parámetros de carga de recompensas"""
        result = super()._loader_params_loyalty_reward()
        
        # Agregar los campos relacionados a productos de precio fijo y dominios de reglas
        result['search_params']['fields'].extend([
            'fixed_price',
            'fixed_price_line_ids',
            'fixed_price_data',
            'fixed_price_map',
            'rules_product_domains'
        ])
        return result
    
    def _get_pos_ui_loyalty_reward(self, params):
        """Cargar recompensas con sus productos asociados y dominios de reglas.
        
        NOTA IMPORTANTE: Los campos fixed_price_data, fixed_price_map y rules_product_domains
        son campos computados con store=True y compute_sudo=True, por lo que Odoo los
        recomputa automáticamente con privilegios de superusuario cuando cambian sus
        dependencias. NO se deben invocar manualmente los métodos _compute_* aquí,
        ya que eso dispararía un write() en loyalty.reward bajo el contexto del usuario
        actual (cajero), quien no tiene permisos de escritura en ese modelo.
        
        Si los datos computados están vacíos, significa que las dependencias no han
        cambiado o que el registro fue creado sin las líneas correspondientes.
        El recálculo se dispara automáticamente al modificar las dependencias desde
        el backend (donde sí hay permisos de administrador).
        """
        rewards = super()._get_pos_ui_loyalty_reward(params)
        
        # Los campos computados stored con compute_sudo=True ya están disponibles
        # en los datos cargados. No es necesario forzar recálculo manual.
        # Si algún campo está vacío, se puede leer con sudo() sin escribir.
        for reward in rewards:
            if reward.get('reward_type') == 'fixed_price':
                if not reward.get('fixed_price_data') or not reward.get('fixed_price_map'):
                    # Leer los valores actuales con sudo (solo lectura, sin escritura)
                    reward_obj = self.env['loyalty.reward'].sudo().browse(reward['id'])
                    reward['fixed_price_data'] = reward_obj.fixed_price_data or []
                    reward['fixed_price_map'] = reward_obj.fixed_price_map or {}
                
                if not reward.get('rules_product_domains'):
                    reward_obj = self.env['loyalty.reward'].sudo().browse(reward['id'])
                    reward['rules_product_domains'] = reward_obj.rules_product_domains or []
        
        return rewards




class LoyaltyRewardFixedPrice(models.Model):
    _name = 'loyalty.reward.fixed.price'
    _description = 'Producto con Precio Fijo'
    _order = 'sequence'

    reward_id = fields.Many2one('loyalty.reward', string='Recompensa', ondelete='cascade', required=True)
    product_id = fields.Many2one('product.product', string='Producto', required=True)
    fixed_price = fields.Float(string='Precio Fijo', required=True, digits='Product Price')
    sequence = fields.Integer(string='Orden', default=10)

    _sql_constraints = [
        ('unique_reward_product', 'UNIQUE(reward_id, product_id)', 
         'No se pueden agregar productos duplicados en la misma recompensa'),
    ]

    def name_get(self):
        result = []
        for record in self:
            name = f"{record.product_id.display_name} - ${record.fixed_price:.2f}"
            result.append((record.id, name))
        return result
    
    @api.model
    def create(self, vals):
        
        # VALIDAR ANTES DE CREAR: ¿Ya existe este producto en esta recompensa?
        existing = self.search([
            ('reward_id', '=', vals.get('reward_id')),
            ('product_id', '=', vals.get('product_id')),
        ], limit=1)
        
        if existing:
            
            return existing;
        
        result = super().create(vals)
        return result
    
class LoyaltyReward(models.Model):
    _inherit = 'loyalty.reward'

    reward_type = fields.Selection(
        selection_add=[('pricelist_change', 'Cambio de Lista de Precios'), ('fixed_price', 'Precio Fijo')],
        ondelete={'pricelist_change': 'cascade', 'fixed_price': 'cascade'}
    )
    pricelist_id = fields.Many2one(
        'product.pricelist', 
        string='Lista de Precios (Recompensa)', 
        store=True,
        help='Lista de precios que se aplicará al cambiar la recompensa'
    )
    fixed_price = fields.Float(string='Precio Fijo', digits='Product Price')
    fixed_price_line_ids = fields.One2many('loyalty.reward.fixed.price', 'reward_id', string='Productos con Precio Fijo')
    
    # CORRECCIÓN: Se agrega compute_sudo=True explícitamente en todos los campos
    # computados stored que acceden a datos de otros modelos. Aunque en Odoo 17+
    # compute_sudo=True es el default para campos stored, lo declaramos explícitamente
    # para mayor claridad y para evitar problemas si el comportamiento default cambia.
    fixed_price_data = fields.Json(
        string='Datos de Precios Fijos', 
        compute='_compute_fixed_price_data', 
        store=True, 
        compute_sudo=True,
        readonly=False
    )
    fixed_price_map = fields.Json(
        string='Mapeo Producto->Precio', 
        compute='_compute_fixed_price_map', 
        store=True,
        compute_sudo=True
    )
    fixed_price_product_ids = fields.Json(
        string='IDs de Productos con Precio Fijo', 
        compute='_compute_fixed_price_product_ids', 
        store=True,
        compute_sudo=True
    )
    rules_product_domains = fields.Json(
        string='Dominios de Productos de Reglas', 
        compute='_compute_rules_product_domains', 
        store=True,
        compute_sudo=True
    )
    
    reward_label = fields.Char(
        string='Etiqueta de Recompensa',
        compute='_compute_reward_label',
        store=True,
        compute_sudo=True,
        help='Etiqueta corta que se mostrará en las líneas del POS cuando se aplique esta recompensa'
    )
    
    reward_badge_color = fields.Selection([
        ('primary', 'Azul'),
        ('success', 'Verde'),
        ('warning', 'Amarillo'),
        ('danger', 'Rojo'),
        ('info', 'Cyan'),
        ('secondary', 'Gris'),
    ], string='Color de Etiqueta', default='success', help='Color del badge en el POS')

    description = fields.Text(
        string='Descripción',
        compute='_compute_description',
        store=True,
        compute_sudo=True,
        help='Descripción de la recompensa, se mostrará en el Punto de Venta'
    )

    @classmethod
    def _pos_ui_export_fields(cls):
        """Exportar campos al POS incluyendo la etiqueta"""
        return super()._pos_ui_export_fields() + [
            'pricelist_id',
            'fixed_price',
            'fixed_price_data',
            'fixed_price_map',
            'fixed_price_product_ids',
            'rules_product_domains',
            'reward_label', 
            'reward_badge_color'  
        ]
    
    @api.depends('reward_type', 'pricelist_id', 'fixed_price_line_ids', 'discount', 'discount_mode')
    def _compute_reward_label(self):
        """Calcula una etiqueta corta para mostrar en las líneas del POS"""
        for record in self:
            if record.reward_type == 'discount':
                if record.discount_mode == 'percent':
                    record.reward_label = f"-{record.discount}%"
                elif record.discount_mode == 'per_order':
                    record.reward_label = f"-${record.discount}"
                else:
                    record.reward_label = "DESCUENTO"
                    
            elif record.reward_type == 'product':
                record.reward_label = "REGALO"
                
            elif record.reward_type == 'pricelist_change':
                if record.pricelist_id:
                    pricelist_name = record.pricelist_id.name
                    record.reward_label = f"💰 {pricelist_name[:15]}"
                else:
                    record.reward_label = "PRECIO ESPECIAL"
                    
            elif record.reward_type == 'fixed_price':
                if record.fixed_price_line_ids:
                    count = len(record.fixed_price_line_ids)
                    record.reward_label = f"💲 PRECIO FIJO ({count})"
                else:
                    record.reward_label = "PRECIO FIJO"
                    
            else:
                record.reward_label = "PROMOCIÓN"
    
    @api.depends('reward_type', 'fixed_price_line_ids', 'fixed_price_line_ids.product_id', 'fixed_price_line_ids.fixed_price')
    def _compute_fixed_price_data(self):
        """Calcula y serializa los datos de precios fijos para exportar al POS"""
        for record in self:
            if record.reward_type == 'fixed_price' and record.fixed_price_line_ids:
                record.fixed_price_data = [
                    {
                        'product_id': line.product_id.id,
                        'product_name': line.product_id.display_name,
                        'fixed_price': line.fixed_price,
                        'sequence': line.sequence,
                    }
                    for line in record.fixed_price_line_ids
                ]
            else:
                record.fixed_price_data = []

    @api.depends('reward_type', 'fixed_price_line_ids', 'fixed_price_line_ids.product_id', 'fixed_price_line_ids.fixed_price')
    def _compute_fixed_price_map(self):
        """Crea un mapeo {product_id: fixed_price} para acceso rápido en POS"""
        for record in self:
            if record.reward_type == 'fixed_price' and record.fixed_price_line_ids:
                record.fixed_price_map = {
                    str(line.product_id.id): line.fixed_price
                    for line in record.fixed_price_line_ids
                }
            else:
                record.fixed_price_map = {}
    
    @api.depends('reward_type', 'fixed_price_line_ids', 'fixed_price_line_ids.product_id')
    def _compute_fixed_price_product_ids(self):
        """Calcula lista de product_ids para validación rápida"""
        for record in self:
            if record.reward_type == 'fixed_price' and record.fixed_price_line_ids:
                record.fixed_price_product_ids = [
                    line.product_id.id for line in record.fixed_price_line_ids
                ]
            else:
                record.fixed_price_product_ids = []

    @api.depends('program_id', 'program_id.rule_ids', 'program_id.rule_ids.product_domain')
    def _compute_rules_product_domains(self):
        """Extrae los dominios de productos de las reglas condicionales"""
        for record in self:
            domains = []
            if record.program_id and record.program_id.rule_ids:
                for rule in record.program_id.rule_ids:
                    if hasattr(rule, 'product_domain') and rule.product_domain:
                        domains.append({
                            'rule_id': rule.id,
                            'rule_name': f"Regla {rule.id}",
                            'product_domain': rule.product_domain,
                        })
            record.rules_product_domains = domains

    @api.depends('reward_type', 'pricelist_id', 'reward_product_ids', 'discount', 'discount_mode', 'fixed_price_line_ids')
    def _compute_description(self):
        for reward in self:
            if reward.reward_type == 'discount':
                if reward.discount_mode == 'percent':
                    reward.description = f"{reward.discount}% de descuento"
                elif reward.discount_mode == 'per_order':
                    reward.description = f"${reward.discount} de descuento"
                else:
                    reward.description = "Recompensa de descuento"

            elif reward.reward_type == 'product':
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
            
            elif reward.reward_type == 'pricelist_change':
                if reward.pricelist_id:
                    reward.description = f"Cambio a lista: {reward.pricelist_id.display_name}"
                else:
                    reward.description = "Cambio de lista de precios"
            
            elif reward.reward_type == 'fixed_price':
                if reward.fixed_price_line_ids:
                    if len(reward.fixed_price_line_ids) == 1:
                        product_name = reward.fixed_price_line_ids[0].product_id.display_name
                        price = reward.fixed_price_line_ids[0].fixed_price
                        reward.description = f"{product_name} a ${price:.2f}"
                    else:
                        reward.description = f"{len(reward.fixed_price_line_ids)} productos con precio fijo"
                else:
                    reward.description = "Precio fijo"

            else: 
                reward.description = "Recompensa de lealtad"

    @api.model
    def create(self, vals):
        if vals.get('reward_type') == 'pricelist_change' and not vals.get('pricelist_id'):
            raise ValidationError("Debe seleccionar una lista de precios para el cambio.")

        result = super(LoyaltyReward, self).create(vals)
        return result

    def write(self, vals):
        """Escribir datos - los campos computados se actualizan automáticamente"""
        result = super(LoyaltyReward, self).write(vals)
        return result

    @api.onchange('reward_type')
    def _onchange_reward_type(self):
        if self.reward_type != 'pricelist_change':
            self.pricelist_id = False

    @api.onchange('pricelist_id')
    def _onchange_pricelist_id(self):
        if self.reward_type == 'pricelist_change' and not self.pricelist_id:
            raise ValidationError("Debe seleccionar una lista de precios para el cambio.")

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
        

        for program in active_programs:
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
        """Verifica si se cumplen las condiciones para aplicar la recompensa"""
        program = reward.program_id
        
        if program.rule_ids:
            for rule in program.rule_ids:
                if rule.minimum_qty and sum(line.product_uom_qty for line in order.order_line) < rule.minimum_qty:
                    return False
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
        """Aplica cambio de lista de precios en backend para POS"""
        if reward.pricelist_id:
            order.write({'pricelist_id': reward.pricelist_id.id})
            return True
        return False

    @api.model
    def _process_order(self, order, draft, existing_order):
        order_id = super(PosOrder, self)._process_order(order, draft, existing_order)
        pos_order = self.browse(order_id)
        
        pricelist_rewards = self.env['loyalty.reward'].search([
            ('reward_type', '=', 'pricelist_change'),
            ('pricelist_id', '!=', False)
        ])

        for reward in pricelist_rewards:
            if reward.program_id.active:
                self._apply_reward_pricelist(reward, pos_order)
        
        return order_id
