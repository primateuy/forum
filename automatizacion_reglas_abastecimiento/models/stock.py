from odoo import fields, models, api


import logging
_logger = logging.getLogger(__name__);

class StockLocation(models.Model):
    _inherit = 'stock.location'

    automate_reordering = fields.Boolean(
        string='Participa en automatización',
        help="Habilita esta ubicación para reglas de reabastecimiento automático"
    )
    
    location_src_id = fields.Many2one(
        'stock.location',
        string='Ubicación de abastecimiento',
        domain="[('usage', '=', 'internal')]",
        help="Desde dónde se repondrá el stock (ej: centro logístico)"
    )
    
    default_min_qty = fields.Float(
        string='Cantidad mínima por defecto',
        default=0,
        help="Cantidad mínima para trigger de reabastecimiento"
    )
    
    default_max_qty = fields.Float(
        string='Cantidad máxima por defecto',
        default=0,
        help="Cantidad máxima para reposición"
    )

class StockRule(models.Model):
    _inherit = 'stock.rule';

    auto_generated = fields.Boolean(string="Generado Automáticamente", default=False)
    is_hierarchical = fields.Boolean(string="Regla Jerárquica", default=False)


class StockWareHouseGroup(models.Model):
    _inherit = 'stock.warehouse.group'

    product_template_ids = fields.One2many(
        'product.template',
        'warehouse_group_id',
        string='Productos en el Grupo de Almacenes'
    )

    product_variant_ids = fields.One2many(
        'product.product',
        'warehouse_group_id',
        string='Variantes de Producto en el Grupo de Almacenes'
    )

    category_rule_ids = fields.One2many(
            'warehouse.group.category.rule',
            'warehouse_group_id',
            string='Reglas por Categoría'
        )
    
    nivel_jerarquia_id = fields.Many2one(
        'niveles.jerarquia',
        string='Nivel de Jerarquía',
        ondelete='set null'
    )

    nivel_jerarquia_nombre = fields.Char(
        string="Nombre del Nivel",
        related='nivel_jerarquia_id.nombre',
        store=False
    )


    def actualizarReglasWizardManual(self):
        """Abre el wizard para actualización manual de reglas"""
        return {
            'name': 'Actualizar Reglas de Abastecimiento',
            'type': 'ir.actions.act_window',
            'res_model': 'stock.warehouse.group.rules.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_warehouse_group_id': self.id,
            }
        }
    
class StockWarehouseGroupRulesWizard(models.TransientModel):
    _name = 'stock.warehouse.group.rules.wizard'
    _description = 'Wizard para actualización en almacenes seleccionados'

    warehouse_group_id = fields.Many2one(
        'stock.warehouse.group',
        string='Grupo de Almacenes',
        required=True,
        readonly=True,
    )

    warehouse_ids = fields.Many2many(
        'stock.warehouse',
        'wizard_warehouse_rel',
        'wizard_id',
        'warehouse_id',
        string='Almacenes',
        required=True,
        help='Seleccione los almacenes donde desea actualizar las reglas',
    )

    available_warehouse_ids = fields.Many2many(
        'stock.warehouse',
        compute='_compute_available_warehouse_ids',
        store=False,
    )

    @api.depends('warehouse_group_id')
    def _compute_available_warehouse_ids(self):
        for record in self:
            if record.warehouse_group_id:
                record.available_warehouse_ids = record.warehouse_group_id.warehouse_ids
            else:
                record.available_warehouse_ids = False

    @api.model
    def default_get(self, fields_list):
        res = super(StockWarehouseGroupRulesWizard, self).default_get(fields_list)
        warehouse_group_id = self.env.context.get('default_warehouse_group_id')
        if warehouse_group_id:
            res['warehouse_group_id'] = warehouse_group_id
        return res

    @api.onchange('warehouse_group_id')
    def _onchange_warehouse_group_id(self):
        if self.warehouse_group_id:
            warehouse_ids = self.warehouse_group_id.warehouse_ids.ids
            if self.warehouse_ids:
                self.warehouse_ids = self.warehouse_ids.filtered(
                    lambda w: w.id in warehouse_ids
                )
            return {'domain': {'warehouse_ids': [('id', 'in', warehouse_ids)]}}
        
        self.warehouse_ids = False
        return {'domain': {'warehouse_ids': [('id', '=', False)]}}

    @api.model
    def default_get(self, fields_list):
        """Establece valores por defecto incluyendo el dominio de almacenes"""
        res = super().default_get(fields_list)
        
        # Si viene el grupo desde el contexto
        warehouse_group_id = self.env.context.get('default_warehouse_group_id')
        if warehouse_group_id:
            grupo = self.env['stock.warehouse.group'].browse(warehouse_group_id)
            _logger.info("Grupo cargado: %s", grupo)
            _logger.info("ALMACENES DEL GRUPO: %s", grupo.warehouse_ids.ids)
            
            # Pre-selecciona todos los almacenes del grupo
            res['warehouse_ids'] = [(6, 0, grupo.warehouse_ids.ids)]
        
        return res

    @api.onchange('warehouse_group_id')
    def _onchange_warehouse_group_id(self):
        """Filtra los almacenes disponibles según el grupo seleccionado"""
        _logger.info("Onchange triggered for warehouse_group_id: %s", self.warehouse_group_id)
        
        if self.warehouse_group_id:
            warehouse_ids = self.warehouse_group_id.warehouse_ids.ids
            _logger.info("Available warehouses in group: %s", warehouse_ids)
            
            # Limpia la selección actual
            self.warehouse_ids = [(5, 0, 0)]  # Elimina todos los registros
            
            return {
                'domain': {
                    'warehouse_ids': [('id', 'in', warehouse_ids)]
                },
                'value': {
                    'warehouse_ids': [(6, 0, warehouse_ids)]  # Pre-selecciona todos los almacenes del grupo
                }
            }
        
        return {
            'domain': {
                'warehouse_ids': []
            },
            'value': {
                'warehouse_ids': [(5, 0, 0)]  # Elimina todos los registros
            }
        }
    
    def actualizarReglas(self):
        """Actualiza las reglas solo para los almacenes seleccionados con procesamiento masivo"""
        if not self.warehouse_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Advertencia',
                    'message': 'Debe seleccionar al menos un almacén',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        # Iniciar procesamiento optimizado
        return self._procesar_reglas_masivo()

    def _procesar_reglas_masivo(self):
        """Procesa las reglas de forma masiva y eficiente"""
        try:
            # 1. Obtener todos los grupos a procesar (actual + jerarquía menor)
            grupos_a_procesar = self._obtener_grupos_jerarquia()
            
            # 2. Obtener todos los productos a procesar de forma optimizada
            productos_totales = self._obtener_productos_masivo(grupos_a_procesar)
            
            # 3. Filtrar almacenes válidos
            almacenes_validos = self._validar_almacenes(grupos_a_procesar)
            
            if not almacenes_validos:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Advertencia',
                        'message': 'Ninguno de los almacenes seleccionados pertenece a los grupos a procesar',
                        'type': 'warning',
                        'sticky': False,
                    }
                }

            # 4. Decidir estrategia según volumen
            total_operaciones = len(productos_totales) * len(almacenes_validos)
            _logger.info("Procesamiento masivo: %d productos x %d almacenes = %d operaciones", 
                        len(productos_totales), len(almacenes_validos), total_operaciones)
            
            if total_operaciones > 500:  # Umbral para procesamiento optimizado
                return self._procesar_en_lotes(productos_totales, almacenes_validos)
            else:
                return self._procesar_directo(productos_totales, almacenes_validos)
                
        except Exception as e:
            _logger.error("Error en procesamiento masivo: %s", str(e))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Error en el procesamiento: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def _obtener_grupos_jerarquia(self):
        """Obtiene todos los grupos a procesar según jerarquía"""
        grupos = [self.warehouse_group_id]
        
        # Agregar grupos de jerarquía menor si existe jerarquía
        if self.warehouse_group_id.nivel_jerarquia_id:
            grupos_menores = self.env['stock.warehouse.group'].search([
                ('nivel_jerarquia_id.seq', '<', self.warehouse_group_id.nivel_jerarquia_id.seq)
            ])
            grupos.extend(grupos_menores)
        
        _logger.info("Grupos a procesar: %s", [g.name for g in grupos])
        return grupos

    def _obtener_productos_masivo(self, grupos):
        """Obtiene todos los productos de forma optimizada usando search en lugar de filtered"""
        grupo_ids = [g.id for g in grupos]
        productos = self.env['product.product'].search([
            ('warehouse_group_id', 'in', grupo_ids)
        ])
        
        _logger.info("Productos encontrados para procesamiento: %d", len(productos))
        return productos

    def _validar_almacenes(self, grupos):
        """Valida que los almacenes seleccionados pertenezcan a los grupos"""
        almacenes_validos = []
        almacenes_grupos_ids = set()
        
        # Recolectar todos los IDs de almacenes de todos los grupos
        for grupo in grupos:
            almacenes_grupos_ids.update(grupo.warehouse_ids.ids)
        
        # Filtrar solo almacenes que pertenecen a algún grupo
        for almacen in self.warehouse_ids:
            if almacen.id in almacenes_grupos_ids:
                almacenes_validos.append(almacen)
        
        _logger.info("Almacenes válidos: %s", [a.name for a in almacenes_validos])
        return almacenes_validos

    def _procesar_directo(self, productos, almacenes):
        """Procesamiento directo para volúmenes pequeños"""
        total_procesados = 0
        errores = 0
        
        for almacen in almacenes:
            for producto in productos:
                try:
                    if producto._actualizar_reglas_abastecimiento(almacen.id):
                        total_procesados += 1
                    else:
                        errores += 1
                except Exception as e:
                    _logger.error("Error procesando producto %s en almacén %s: %s", 
                                 producto.name, almacen.name, str(e))
                    errores += 1

        return self._generar_notificacion_resultado(total_procesados, errores, almacenes)

    def _procesar_en_lotes(self, productos, almacenes):
        """Procesamiento en lotes para volúmenes grandes"""
        total_procesados = 0
        errores = 0
        lote_size = 50  # Procesar de a 50 productos por vez
        
        productos_list = list(productos)
        total_productos = len(productos_list)
        
        for almacen in almacenes:
            _logger.info("Procesando almacén: %s", almacen.name)
            
            # Procesar en lotes
            for i in range(0, total_productos, lote_size):
                lote_productos = productos_list[i:i+lote_size]
                
                # Usar savepoint para cada lote
                with self.env.cr.savepoint():
                    for producto in lote_productos:
                        try:
                            if producto._actualizar_reglas_abastecimiento(almacen.id):
                                total_procesados += 1
                            else:
                                errores += 1
                        except Exception as e:
                            _logger.error("Error procesando producto %s: %s", 
                                         producto.name, str(e))
                            errores += 1
                
                # Commit intermedio para no perder progreso
                self.env.cr.commit()
                
                # Log de progreso cada 100 productos
                if (i + lote_size) % 100 == 0:
                    progreso = min(((i + lote_size) / total_productos) * 100, 100)
                    _logger.info("Progreso almacén %s: %.1f%% (%d/%d)", 
                               almacen.name, progreso, i + lote_size, total_productos)

        return self._generar_notificacion_resultado(total_procesados, errores, almacenes)

    def _generar_notificacion_resultado(self, total_procesados, errores, almacenes):
        
        
        if errores == 0:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Reglas Actualizadas Exitosamente',
                    'message': f'Se procesaron {total_procesados} reglas en almacenes',
                    'type': 'success',
                    'sticky': False,
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Procesamiento Completado con Advertencias',
                    'message': f'Éxitos: {total_procesados}, Errores: {errores}. Almacenes: {almacenes_nombres}. Revise los logs para detalles.',
                    'type': 'warning',
                    'sticky': True,
                }
            }
