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
        
        
        result['search_params']['fields'].extend([
            'fixed_price',
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
        """Aplica cambio de lista de precios en backend para POS.
        Usado solo cuando se debe forzar la pricelist y el payload no la trae."""
        if reward.pricelist_id:
            order.write({'pricelist_id': reward.pricelist_id.id})
            return True
        return False

    @api.model
    def _process_order(self, order, draft, existing_order):
        """
        Procesa la orden del POS sin sobrescribir datos que ya vienen del frontend.

        El frontend (pricelistReward.js) ya envía pricelist_id en el payload cuando
        el cliente califica para la recompensa pricelist_change. Hacer write() aquí
        sobre pricelist_id después de super() puede:
        - Sobrescribir con una lista incorrecta si hay varios programas con
          pricelist_change (se aplicaban todos en bucle y ganaba el último).
        - Interferir con el módulo de lealtad (advanced_loyalty_management / estándar),
          que aplica los puntos en la misma transacción; el write() puede alterar
          el estado de la orden y provocar que los puntos no se persistan.

        Por tanto, no aplicamos pricelist en backend: confiamos en el pricelist_id
        que envía el frontend. Si en el futuro se necesita aplicar pricelist solo
        cuando el payload no la trae, debe comprobarse order.get('data', {}).get('pricelist_id')
        y aplicar solo en ese caso, y preferiblemente solo la recompensa realmente
        reclamada en la orden (no todas las activas).
        """



        order_data = order.get("data") if isinstance(order, dict) else order
        cpc = order_data.get("coupon_point_changes") if isinstance(order_data, dict) else None

        result = super(PosOrder, self)._process_order(order, draft, existing_order)

        # Aplicar puntos de lealtad al cupón/tarjeta cuando el payload trae coupon_point_changes.
        if not draft and cpc and isinstance(cpc, dict) and self.env.get('loyalty.card'):

            self._apply_coupon_point_changes(cpc)

        return result

    @api.model
    def create_from_ui(self, orders, draft=False):
        """
        Crea órdenes desde la UI y aplica coupon_point_changes a loyalty.card.

        Dependemos de odoo_pos_no_invoice para que este método se ejecute primero en la
        cadena (MRO) y así tengamos acceso al payload antes de que otros módulos lo consuman.
        Extraemos coupon_point_changes ANTES de super() porque el core/sync puede modificar
        o reemplazar la lista orders; aplicamos los puntos DESPUÉS de super() para que la
        orden ya esté creada.
        
       
        """
        coupon_point_changes_with_partner = []
        for order_payload in (orders or []):
            if not isinstance(order_payload, dict):
                coupon_point_changes_with_partner.append((None, None))
                continue
            order_data = order_payload.get('data') or order_payload
            if not isinstance(order_data, dict):
                coupon_point_changes_with_partner.append((None, None))
                continue
            cpc = order_data.get('coupon_point_changes') if order_data.get('coupon_point_changes') else None
            partner_id = order_data.get('partner_id') if order_data.get('partner_id') else None
            if cpc and isinstance(cpc, dict) and partner_id:
                coupon_point_changes_with_partner.append((cpc, partner_id))
            else:
                coupon_point_changes_with_partner.append((None, None))

        result = super(PosOrder, self).create_from_ui(orders, draft)

        if draft:
            return result
        
        try:
            self.env['loyalty.card']
        except KeyError:
            _logger.debug(
                "[cambio_precio] create_from_ui: modelo loyalty.card no disponible, no se aplican puntos"
            )
            return result

        num_cpc = sum(1 for cpc, _ in coupon_point_changes_with_partner if cpc)
        if num_cpc:
            _logger.info(
                "[cambio_precio] create_from_ui: aplicando puntos en %s orden(es)",
                num_cpc,
            )


        for cpc, order_partner_id in coupon_point_changes_with_partner:
            if cpc:
                _logger.info(
                    "[cambio_precio] create_from_ui: aplicando coupon_point_changes keys=%s partner=%s",
                    list(cpc.keys()), order_partner_id
                )
                self._apply_coupon_point_changes(cpc, order_partner_id)

        return result

    @api.model
    def _apply_coupon_point_changes(self, coupon_point_changes, partner_id=None):
        """Aplica cambios de puntos de cupón a las tarjetas de lealtad.
        """
        if not coupon_point_changes or not isinstance(coupon_point_changes, dict):
            _logger.debug("[cambio_precio] coupon_point_changes vacío o inválido, saltando")
            return
            
        LoyaltyCard = self.env['loyalty.card']
        
        for card_id_str, change in coupon_point_changes.items():
            if not change or not isinstance(change, dict):
                _logger.debug("[cambio_precio] cambio vacío para card %s, saltando", card_id_str)
                continue
                
            points = change.get('points')
            if points is None:
                _logger.debug("[cambio_precio] sin 'points' en cambio para card %s", card_id_str)
                continue

            try:
                card_id = int(card_id_str)
            except (TypeError, ValueError):
                _logger.warning("[cambio_precio] id de tarjeta no válido: %s (tipo: %s)", 
                               card_id_str, type(card_id_str).__name__)
                continue

            program_id = change.get('program_id')
            if not program_id:
                _logger.warning(
                    "[cambio_precio] Cambio de puntos sin program_id para tarjeta %s. "
                    "Saltando porque las tarjetas requieren un programa asociado.",
                    card_id_str
                )
                continue

            card = LoyaltyCard.sudo().browse(card_id)

            if not card.exists():
                program = self.env['loyalty.program'].sudo().browse(program_id)
                if not program.exists():
                    _logger.error(
                        "[cambio_precio] Programa %s no existe. No se puede crear loyalty.card %s. "
                        "Verifica que el programa_id está correctamente configurado en las recompensas.",
                        program_id, card_id_str
                    )
                    continue

                if not partner_id:
                    _logger.warning(
                        "[cambio_precio] No se puede crear loyalty.card %s sin partner_id. "
                        "Las tarjetas requieren cliente asociado.",
                        card_id_str
                    )
                    continue

                existing_card = LoyaltyCard.sudo().search([
                    ('program_id', '=', program_id),
                    ('partner_id', '=', partner_id),
                ], limit=1)
                
                if existing_card:
                    _logger.info(
                        "[cambio_precio] Tarjeta duplicada detectada: program=%s partner=%s. "
                        "Usando tarjeta existente id=%s en lugar de crear nueva.",
                        program_id, partner_id, existing_card.id
                    )
                    card = existing_card
                else:
                    try:
                        with self.env.cr.savepoint():
                            card = LoyaltyCard.sudo().create({
                                'program_id': program_id,
                                'partner_id': partner_id,
                                'points': 0,
                            })
                            _logger.info(
                                "[cambio_precio] loyalty.card creada: id=%s program=%s partner=%s",
                                card.id, program_id, partner_id
                            )
                    except Exception as e:
                        _logger.error(
                            "[cambio_precio] Error creando loyalty.card para programa %s: %s",
                            program_id, str(e)
                        )
                        continue
            else:
                if not card.program_id:
                    _logger.warning(
                        "[cambio_precio] Tarjeta %s existe pero sin program_id. No se pueden aplicar puntos.",
                        card.id
                    )
                    continue

            try:
                with self.env.cr.savepoint():
                    card_for_update = LoyaltyCard.sudo().browse(card.id)
                    current_points = card_for_update.points or 0
                    new_points = current_points + points
                    
                    card_for_update.write({'points': new_points})
                    _logger.info(
                        "[cambio_precio] card %s +%s puntos (nuevo total: %s)",
                        card.id, points, new_points
                    )
            except Exception as e:
                _logger.error(
                    "[cambio_precio] Error actualizando puntos en tarjeta %s: %s",
                    card.id, str(e)
                )