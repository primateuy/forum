
from odoo import models, fields, api
from odoo.exceptions import ValidationError

import logging
_logger = logging.getLogger(__name__);

class ProductProduct(models.Model):
    _inherit = 'product.product'
    
    warehouse_group_id = fields.Many2one(
        'stock.warehouse.group',
        string="Grupo de Almacenes",
        help="Define a qué grupo de almacenes pertenece esta variante",
    )

    def botonListaReglas(self):
        contador = 0;
        for product in self:
            product.generarReglasAbastecimiento();
            contador += 1;

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Reglas Generadas',
                'message': f'Se generaron reglas para {contador} variantes',
                'type': 'success',
                'sticky': False,
            }
        }

    def _actualizar_reglas_abastecimiento(self, almacen_id):
        almacen = self.env['stock.warehouse'].browse(almacen_id)
    
        if not almacen:
            return False

        existing_rules = self.env['stock.warehouse.orderpoint'].search([
            ('product_id', '=', self.id),
            ('warehouse_id', '=', almacen.id),
            ('company_id', '=', self.env.company.id)
        ])
        if existing_rules:
            existing_rules.unlink()

        ubicaciones = self.env['stock.location'].search([
            ('usage', '=', 'internal'),
            ('id', 'child_of', almacen.view_location_id.id),
            ('replenish_location', '=', True),
            ('automate_reordering', '=', True)
        ])

        if not ubicaciones:
            return True

        categoriaGrupo = False
        if self.warehouse_group_id and self.warehouse_group_id.category_rule_ids:
            for cat in self.warehouse_group_id.category_rule_ids:
                if cat.categ_id.id == self.categ_id.id:
                    categoriaGrupo = cat
                    break

        reglas_data = []
        for ubicacion in ubicaciones:
            regla_data = {
                'product_id': self.id,
                'location_id': ubicacion.id,
                'warehouse_id': almacen.id,
                'product_min_qty': categoriaGrupo.min_qty if categoriaGrupo and categoriaGrupo.min_qty else ubicacion.default_min_qty,
                'product_max_qty': categoriaGrupo.max_qty if categoriaGrupo and categoriaGrupo.max_qty else ubicacion.default_max_qty,
                'qty_multiple': categoriaGrupo.qty_multiple if categoriaGrupo and categoriaGrupo.use_multiples else 1,
                'company_id': self.env.company.id
            }
            reglas_data.append(regla_data)

        if len(reglas_data) > 20:
            self.actualizar_reglas_masivo([self.id], [almacen.id], lote_size=20);
        else:
            self.env['stock.warehouse.orderpoint'].create(reglas_data)

        return True

    @api.model
    def actualizar_reglas_masivo(self, product_ids, almacen_ids, lote_size=50):
        
        estadisticas = {
            'productos_procesados': 0,
            'reglas_creadas': 0,
            'errores': 0,
            'tiempo_inicio': fields.Datetime.now()
        }

        productos = self.browse(product_ids)
        total_productos = len(productos)
        
        

        try:
            for i in range(0, total_productos, lote_size):
                lote_productos = productos[i:i+lote_size]
                lote_actual = i // lote_size + 1
                total_lotes = (total_productos + lote_size - 1) // lote_size
                
                
                # Usar savepoint para proteger cada lote
                with self.env.cr.savepoint():
                    for producto in lote_productos:
                        for almacen_id in almacen_ids:
                            try:
                                if producto._actualizar_reglas_abastecimiento(almacen_id):
                                    estadisticas['productos_procesados'] += 1
                                else:
                                    estadisticas['errores'] += 1
                            except Exception as e:
                                estadisticas['errores'] += 1

                self.env.cr.commit()
                

        except Exception as e:
            estadisticas['errores'] += 1

        estadisticas['tiempo_fin'] = fields.Datetime.now()
        
        return estadisticas

    def reglasDesdeWarehouseGroup(self, warehouse_id):
        for product in self:

            

            warehouse = self.env['stock.warehouse'].browse(warehouse_id);

            if not warehouse:
                continue

            

            categoriaGrupo = '';


            for group in warehouse.warehouse_group_ids:
                if group.id == product.warehouse_group_id.id:
                    for cat in group.category_rule_ids:
                        if cat.categ_id.id == product.categ_id.id:
                            categoriaGrupo = cat
                            break
            
            


            grupoActual = product.warehouse_group_id;
            ubicacionesActual = self.env['stock.location'].search([
                    ('usage', '=', 'internal'),
                    ('id', 'child_of', warehouse.view_location_id.id),
                    ('replenish_location', '=', True),
                    ('automate_reordering', '=', True)
                ]);
            
            for ub in ubicacionesActual:
                existing_rules = product.env['stock.warehouse.orderpoint'].search([
                    ('product_id', '=', product.id),
                    ('company_id', '=', product.env.company.id),
                    ('warehouse_id', '=', warehouse.id)
                ])
                if existing_rules:
                    existing_rules.unlink()

                product.env['stock.warehouse.orderpoint'].create({
                    'product_id': product.id,
                    'location_id': ub.id,
                    'warehouse_id': warehouse.id,
                    'product_min_qty': categoriaGrupo.min_qty if categoriaGrupo and categoriaGrupo.min_qty else ub.default_min_qty,
                    'product_max_qty': categoriaGrupo.max_qty if categoriaGrupo and categoriaGrupo.max_qty else ub.default_max_qty,
                    'qty_multiple': categoriaGrupo.qty_multiple if categoriaGrupo and categoriaGrupo.use_multiples else 1,
                    'company_id': product.env.company.id
                })

            restoGrupos = [];



            if product.warehouse_group_id.nivel_jerarquia_id:
                grupos_jerarquia = product.env['stock.warehouse.group'].search([
                    ('nivel_jerarquia_id.seq', '<', product.warehouse_group_id.nivel_jerarquia_id.seq),
                    ('id', '!=', product.warehouse_group_id.id)
                ])
                restoGrupos += (grupos_jerarquia)

            for grupo in restoGrupos:

                for alm in grupo.warehouse_ids:

                    ubicaciones_internas = product.env['stock.location'].search([
                            ('usage', '=', 'internal'),
                            ('id', 'child_of', alm.view_location_id.id),
                            ('replenish_location', '=', True),
                            ('automate_reordering', '=', True)
                        ])

                    for ubicacion in ubicaciones_internas:

                        if categoriaGrupo and categoriaGrupo.use_multiples and categoriaGrupo.qty_multiple <= 0:
                            raise ValidationError("Se encontró la categoría pero la misma tiene un múltiplo menor o igual a 0")

                        existing_rules = product.env['stock.warehouse.orderpoint'].search([
                            ('product_id', '=', product.id),
                            ('company_id', '=', product.env.company.id),
                            ('warehouse_id', '=', warehouse.id)
                        ])
                        if existing_rules:
                            existing_rules.unlink()

                        product.env['stock.warehouse.orderpoint'].create({
                            'product_id': product.id,
                            'location_id': ubicacion.id,
                            'warehouse_id': warehouse.id,
                            'product_min_qty': categoriaGrupo.min_qty if categoriaGrupo and categoriaGrupo.min_qty else ubicacion.default_min_qty,
                            'product_max_qty': categoriaGrupo.max_qty if categoriaGrupo and categoriaGrupo.max_qty else ubicacion.default_max_qty,
                            'qty_multiple': categoriaGrupo.qty_multiple if categoriaGrupo and categoriaGrupo.use_multiples else 1,
                            'company_id': product.env.company.id
                        })
            



            

    def generarReglasAbastecimiento(self):
        
        productos_con_grupo = self.filtered(lambda p: p.warehouse_group_id)
        
        if not productos_con_grupo:
            return
        
        total_productos = len(productos_con_grupo)
        
        tiempo_inicio = fields.Datetime.now()
        
        # Obtener todos los grupos únicos involucrados
        grupos_ids = productos_con_grupo.mapped('warehouse_group_id').ids
        grupos = self.env['stock.warehouse.group'].browse(grupos_ids)
        
        # Pre-cargar niveles de jerarquía y grupos relacionados
        grupos_con_jerarquia = grupos.filtered(lambda g: g.nivel_jerarquia_id)
        max_seq = max(grupos_con_jerarquia.mapped('nivel_jerarquia_id.seq')) if grupos_con_jerarquia else 0
        
        # Cargar todos los grupos que podrían ser necesarios
        todos_grupos = self.env['stock.warehouse.group'].search([
            ('nivel_jerarquia_id.seq', '<=', max_seq)
        ]) if max_seq > 0 else grupos
        
        # Pre-cargar todas las relaciones de categorías
        categorias_por_grupo = {}
        for grupo in todos_grupos:
            categorias_por_grupo[grupo.id] = {
                cat.categ_id.id: cat 
                for cat in grupo.category_rule_ids
            }
        
        # Pre-cargar todos los almacenes y ubicaciones
        almacenes_por_grupo = {}
        ubicaciones_por_almacen = {}
        
        for grupo in todos_grupos:
            almacenes_por_grupo[grupo.id] = grupo.warehouse_ids.ids
            
            for almacen in grupo.warehouse_ids:
                if almacen.id not in ubicaciones_por_almacen:
                    ubicaciones = self.env['stock.location'].search([
                        ('usage', '=', 'internal'),
                        ('id', 'child_of', almacen.view_location_id.id),
                        ('replenish_location', '=', True),
                        ('automate_reordering', '=', True)
                    ])
                    ubicaciones_por_almacen[almacen.id] = ubicaciones
        
        
        # OPTIMIZACIÓN 2: Eliminar todas las reglas existentes en una sola operación
        reglas_existentes = self.env['stock.warehouse.orderpoint'].search([
            ('product_id', 'in', productos_con_grupo.ids),
            ('company_id', '=', self.env.company.id)
        ])
        
        if reglas_existentes:
            reglas_existentes.unlink()

        todas_reglas = []
        productos_procesados = 0
        errores = 0
        
        for product in productos_con_grupo:
            try:
                grupos_a_procesar = []
                
                if product.warehouse_group_id.nivel_jerarquia_id:
                    seq_producto = product.warehouse_group_id.nivel_jerarquia_id.seq
                    grupos_a_procesar = [
                        g for g in todos_grupos 
                        if g.nivel_jerarquia_id and g.nivel_jerarquia_id.seq <= seq_producto
                    ]
                else:
                    grupos_a_procesar = [product.warehouse_group_id]
                
                for grupo in grupos_a_procesar:
                    almacenes_ids = almacenes_por_grupo.get(grupo.id, [])
                    categorias_grupo = categorias_por_grupo.get(grupo.id, {})
                    categoria_producto = categorias_grupo.get(product.categ_id.id, False)
                    
                    for almacen_id in almacenes_ids:
                        ubicaciones = ubicaciones_por_almacen.get(almacen_id, [])
                        
                        if (categoria_producto and 
                            categoria_producto.use_multiples and 
                            categoria_producto.qty_multiple <= 0):
                            
                            continue
                        
                        for ubicacion in ubicaciones:
                            regla_data = {
                                'product_id': product.id,
                                'location_id': ubicacion.id,
                                'warehouse_id': almacen_id,
                                'product_min_qty': (
                                    categoria_producto.min_qty 
                                    if categoria_producto and categoria_producto.min_qty 
                                    else ubicacion.default_min_qty
                                ),
                                'product_max_qty': (
                                    categoria_producto.max_qty 
                                    if categoria_producto and categoria_producto.max_qty 
                                    else ubicacion.default_max_qty
                                ),
                                'qty_multiple': (
                                    categoria_producto.qty_multiple 
                                    if categoria_producto and categoria_producto.use_multiples 
                                    else 1
                                ),
                                'company_id': self.env.company.id
                            }
                            todas_reglas.append(regla_data)
                
                productos_procesados += 1
                
                
                    
            except Exception as e:
                errores += 1
                
        
        
        
        LOTE_SIZE = 500
        reglas_creadas = 0
        
        for i in range(0, len(todas_reglas), LOTE_SIZE):
            lote = todas_reglas[i:i+LOTE_SIZE]
            try:
                self.env['stock.warehouse.orderpoint'].create(lote)
                reglas_creadas += len(lote)
                
                if i > 0 and i % (LOTE_SIZE * 5) == 0:
                    self.env.cr.commit()
                    
            except Exception as e:
                errores += 1
        
        

    def write(self, vals):
        res = super(ProductProduct, self).write(vals)

        if 'warehouse_group_id' in vals or 'categ_id' in vals:
            self.generarReglasAbastecimiento()
                
        return res;

    def crear100Almacenes(self):
        for i in range(200, 300):
            nombre_almacen = f'Almacén {i}'
            
            # Crear el almacén
            almacen = self.env['stock.warehouse'].create({
                'name': nombre_almacen,
                'code': f'WH{i:03}',
                'partner_id': self.env.company.partner_id.id,
            })
            
            self._configurar_ubicaciones_automatizacion(almacen)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Almacenes Creados',
                'message': 'Se crearon 100 almacenes con ubicaciones configuradas para automatización',
                'type': 'success',
                'sticky': False,
            }
        }

    def _configurar_ubicaciones_automatizacion(self, almacen):
        """Configura las ubicaciones del almacén para participar en automatización"""
        
        # Buscar ubicaciones internas del almacén
        ubicaciones_internas = self.env['stock.location'].search([
            ('usage', '=', 'internal'),
            ('id', 'child_of', almacen.view_location_id.id),
            ('id', '!=', almacen.view_location_id.id)  # Excluir la vista principal
        ])
        
        for ubicacion in ubicaciones_internas:
            # Habilitar automatización y establecer cantidades por defecto
            ubicacion.write({
                'automate_reordering': True,
                'replenish_location': True,
                'default_min_qty': 10.0,  # Cantidad mínima por defecto
                'default_max_qty': 100.0,  # Cantidad máxima por defecto
                'location_src_id': ubicacion.id,  # Puede ser otra ubicación si necesario
            })
        
        # Si no hay ubicaciones internas, crear una por defecto
        if not ubicaciones_internas:
            self.env['stock.location'].create({
                'name': f'Stock {almacen.name}',
                'location_id': almacen.lot_stock_id.id,
                'usage': 'internal',
                'automate_reordering': True,
                'replenish_location': True,
                'default_min_qty': 10.0,
                'default_max_qty': 100.0,
            })


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    warehouse_group_id = fields.Many2one(
        'stock.warehouse.group',
        string="Grupo de Almacenes",
        help="Define a qué grupo de almacenes pertenece esta variante",
    )

    def crear100Almacenes(self):
        """Crea 100 almacenes con ubicaciones preconfiguradas para automatización"""
        for i in range(1, 101):
            nombre_almacen = f'Almacén {i}'
            
            # Crear el almacén
            almacen = self.env['stock.warehouse'].create({
                'name': nombre_almacen,
                'code': f'WH{i:03}',
                'partner_id': self.env.company.partner_id.id,
            })
            
            # Configurar las ubicaciones del almacén para automatización
            self._configurar_ubicaciones_automatizacion(almacen)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Almacenes Creados',
                'message': 'Se crearon 100 almacenes con ubicaciones configuradas para automatización',
                'type': 'success',
                'sticky': False,
            }
        }

    def _configurar_ubicaciones_automatizacion(self, almacen):
        """Configura las ubicaciones del almacén para participar en automatización"""
        
        # Buscar ubicaciones internas del almacén
        ubicaciones_internas = self.env['stock.location'].search([
            ('usage', '=', 'internal'),
            ('id', 'child_of', almacen.view_location_id.id),
            ('id', '!=', almacen.view_location_id.id)  # Excluir la vista principal
        ])
        
        for ubicacion in ubicaciones_internas:
            # Habilitar automatización y establecer cantidades por defecto
            ubicacion.write({
                'automate_reordering': True,
                'replenish_location': True,
                'default_min_qty': 10.0,  # Cantidad mínima por defecto
                'default_max_qty': 100.0,  # Cantidad máxima por defecto
                'location_src_id': ubicacion.id,  # Puede ser otra ubicación si necesario
            })
        
        # Si no hay ubicaciones internas, crear una por defecto
        if not ubicaciones_internas:
            self.env['stock.location'].create({
                'name': f'Stock {almacen.name}',
                'location_id': almacen.lot_stock_id.id,
                'usage': 'internal',
                'automate_reordering': True,
                'replenish_location': True,
                'default_min_qty': 10.0,
                'default_max_qty': 100.0,
            })


    def botonListaReglas(self):
        
        for product in self:
            if product.product_variant_ids:
                product.product_variant_ids.with_context(skip_auto_rules=True).generarReglasAbastecimiento()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Reglas Generadas',
                'message': f'Se generaron reglas para {len(self.product_variant_ids)} variantes',
                'type': 'success',
                'sticky': False,
            }
        }



    def generarReglasAbastecimiento(self):
        if self.product_variant_ids:
            self.product_variant_ids.with_context(skip_auto_rules=True).generarReglasAbastecimiento()
            
         
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Reglas Generadas',
                'message': f'Se generaron reglas para {len(self.product_variant_ids)} variantes',
                'type': 'success',
                'sticky': False,
            }
        }

    def write(self, vals):
            res = super(ProductTemplate, self).write(vals)
            
            if 'warehouse_group_id' in vals and not self._context.get('skip_auto_rules'):
                self.product_variant_ids.with_context(skip_auto_rules=True).write({
                    'warehouse_group_id': self.warehouse_group_id.id,
                })
                

                for variante in self.product_variant_ids:
                    variante.warehouse_group_id = self.warehouse_group_id
                    variante.generarReglasAbastecimiento()
                
                
                
            return res
    

 
    @api.model
    def create(self, vals):
        template = super(ProductTemplate, self).create(vals)
        
        if 'warehouse_group_id' in vals:
            template.product_variant_ids.with_context(skip_auto_rules=True).write({
                'warehouse_group_id': template.warehouse_group_id.id,
            })
            
            template.product_variant_ids.generarReglasAbastecimiento()

        return template