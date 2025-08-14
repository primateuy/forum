from odoo import fields, api, models
import logging
from odoo.exceptions import ValidationError
import math

_logger = logging.getLogger(__name__)

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'
    
    crossdock_enabled = fields.Boolean(
        string="Crossdock habilitado",
        default=False
    )

    crossdock_percentage = fields.Float(
        string="Porcentaje por defecto para las líneas",
        default=80.0
    )

    distribution_rounding_method = fields.Selection([
        ('nearest', 'Redondeo a múltiplo más cercano'),
        ('floor', 'Redondeo a múltiplo inferior'),
        ('ceil', 'Redondeo a múltiplo superior')
    ], default='nearest', string="Metódo de Redondeo");

    crossdock_lines_count = fields.Integer(
        string='Líneas Crossdock',
        compute='_compute_crossdock_lines_count'
    )

    @api.depends('order_line.use_crossdock')
    def _compute_crossdock_lines_count(self):
        """Contar líneas con crossdocking habilitado"""
        for record in self:
            record.crossdock_lines_count = len(record.order_line.filtered('use_crossdock'))

    def action_edit_crossdock_distribution(self):
        """Abrir wizard de edición de distribución"""
        # Validar que haya líneas con crossdocking
        crossdock_lines = self.order_line.filtered('use_crossdock')
        if not crossdock_lines:
            raise ValidationError("No hay líneas con crossdocking habilitado para distribuir.")
        
        return {
            'name': 'Editar Distribución Crossdocking',
            'type': 'ir.actions.act_window',
            'res_model': 'crossdock.distribution.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_purchase_order_id': self.id,
                'active_model': 'purchase.order',
                'active_id': self.id,
            }
        }
    
    def _create_crossdock_picking(self, order_line, distributions):
        """Crear picking de crossdocking con múltiples destinos"""
        
        # 1. Obtener ubicaciones
        source_location = self.picking_type_id.default_location_dest_id  # Donde llega la mercadería
        
        # 2. Agrupar distribuciones que van al mismo almacén
        warehouse_groups = {}
        for dist in distributions:
            warehouse_id = dist['warehouse'].id
            if warehouse_id not in warehouse_groups:
                warehouse_groups[warehouse_id] = {
                    'warehouse': dist['warehouse'],
                    'total_quantity': 0,
                    'is_principal': dist['is_principal']
                }
            warehouse_groups[warehouse_id]['total_quantity'] += dist['quantity']
        
        for warehouse_id, group in warehouse_groups.items():
            if group['total_quantity'] <= 0:
                continue
                
            warehouse = group['warehouse']
            
            picking_vals = {
                'picking_type_id': self._get_crossdock_picking_type(warehouse).id,
                'partner_id': self.partner_id.id,
                'origin': f"Crossdock {self.name}",
                'location_id': source_location.id,
                'location_dest_id': warehouse.lot_stock_id.id,
                'state': 'draft',
                'move_type': 'direct',
                
            }
            
            picking = self.env['stock.picking'].create(picking_vals)
            
            move_vals = {
                'name': f"Crossdock: {order_line.product_id.display_name}",
                'product_id': order_line.product_id.id,
                'product_uom_qty': group['total_quantity'],
                'product_uom': order_line.product_uom.id,
                'picking_id': picking.id,
                'location_id': source_location.id,
                'location_dest_id': warehouse.lot_stock_id.id,
                'origin': f"PO {self.name}",
                'state': 'draft',
                'warehouse_id': warehouse.id,
            }
            
            move = self.env['stock.move'].create(move_vals)
            
            try:
                picking.action_confirm()
                picking.action_assign()
                
                if hasattr(self, 'auto_validate_crossdock') and self.auto_validate_crossdock:
                    for move_line in picking.move_line_ids:
                        move_line.qty_done = move_line.product_uom_qty
                    
                    picking.button_validate();
                    
            except Exception as e:
                _logger.error(f"Error procesando picking {picking.name}: {str(e)}")
                # Opcional: enviar mensaje al usuario
                self.message_post(
                    body=f"⚠️ Error en crossdocking para {order_line.product_id.display_name}: {str(e)}"
                )

    def _get_crossdock_picking_type(self, target_warehouse):
        crossdock_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('warehouse_id', '=', self.picking_type_id.warehouse_id.id),
            ('name', 'ilike', 'crossdock')
        ], limit=1)
        
        if not crossdock_type:
            # Crear tipo de picking si no existe
            crossdock_type = self.env['stock.picking.type'].create({
                'name': 'Crossdocking',
                'code': 'internal',
                'sequence_code': 'CROSS',
                'warehouse_id': self.picking_type_id.warehouse_id.id,
                'default_location_src_id': self.picking_type_id.default_location_dest_id.id,
                'default_location_dest_id': target_warehouse.lot_stock_id.id,
                'use_create_lots': False,
                'use_existing_lots': True,
            })
        
        return crossdock_type


    def redondeo(self, val, multiplo = 1):

        if self.distribution_rounding_method == 'nearest':
            return round(val * multiplo);

        elif self.distribution_rounding_method == 'floor':
            return math.floor(val * multiplo);

        else:
            return math.ceil(val * multiplo);

    def button_confirm(self, *args, **kwargs):
        res = super(PurchaseOrder, self).button_confirm(*args, **kwargs)

        for order in self:
            if order.crossdock_enabled:
                
                order._generate_crossdock_moves()

        return res


    def _generate_crossdock_moves(self):
        for line in self.order_line.filtered(lambda l: l.use_crossdock):
            setuAdvanceReordering = self.env['ir.module.module'].sudo().search([
                ('name', '=', 'setu_advance_reordering'),
                ('state', '=', 'installed')
            ], limit=1)

            moduloReglasAbastecimiento = self.env['ir.module.module'].sudo().search([
                ('name', '=', 'automatizacion_reglas_abastecimiento'),
                ('state', '=', 'installed')
            ], limit=1);
            
            porcentaje  = 0;
            if line.line_crossdock_percentage:
                porcentaje = line.line_crossdock_percentage;
            else:
                porcentaje = self.crossdock_percentage / 100;
    


            if setuAdvanceReordering and moduloReglasAbastecimiento:
                if not line.product_id.warehouse_group_id:
                    
                    return;

                if not line.use_crossdock:
                    return;
        
                categoriaProducto = line.product_id.categ_id;


                grupoProducto = line.product_id.warehouse_group_id;       

                categoriasGrupo = grupoProducto.category_rule_ids;
                almacenesEncontrados = grupoProducto.warehouse_ids;        
                cantidadAlmacenes = len(almacenesEncontrados) - 1;


                if not almacenesEncontrados:
                    self.message_post(
                                body="No hay almacenes disponibles."
                            )
                    continue;

                if not categoriasGrupo:
                    raise ValidationError("El grupo no posee categorias.");

                for cat in categoriasGrupo:
                    if categoriaProducto.id == cat.id:
                        



                        for almacen in almacenesEncontrados:
                            if almacen.id == '1':
                                cantidadAlmacenes -= 1;
                        
                        
                        


                        if not porcentaje:
                            raise ValueError("No se encontró un porcentaje valido.");

                        if not line.distribution_multiple:
                            raise ValueError("El número para distribución multiplo no es valido");
                        
                        categoriaProducto = line.product_id.categ_id;

                        grupo = line.product_id.warehouse_group_id;

                        if not grupo.warehouse_ids:
                            self.message_post(
                                
                                body="No hay almacenes disponibles."
                            )
                            continue;


                        for cat in grupo.category_rule_ids:
                            if categoriaProducto.id == cat.id:
                                if line.product_qty > cat.max_qty or line.product_qty < cat.min_qty:
                                    raise ValidationError(f"Las cantidades deben estar dentro del rango {cat.min_qty} - {cat.max_qty}")
                        


                        cantidadPorcentaje = line.product_qty * porcentaje;

                        restante = round(line.product_qty - cantidadPorcentaje);

                        if cantidadAlmacenes == 0:
                            cantidadAlmacenes -= 1;


                        valorPerAlmacen = self.redondeo(cantidadPorcentaje / cantidadAlmacenes, line.distribution_multiple);

                        if valorPerAlmacen <= 0 or valorPerAlmacen % line.distribution_multiple != 0:
                            self.message_post(
                                body=f"La cantidad calculada ({valorPerAlmacen}) para {line.product_id.display_name} "
                                f"no cumple con el múltiplo {line.distribution_multiple}. "
                                "No se puede generar distribución automática."
                            )
                            continue;


                        distributions = []

                        for almacen in almacenesEncontrados:
                            if almacen.id == 1 and len(almacenesEncontrados) == 1:
                                # Solo hay almacén principal
                                distributions.append({
                                    'warehouse': almacen,
                                    'quantity': line.product_qty,
                                    'is_principal': True
                                })
                                
                            elif almacen.id == 1:
                                # Almacén principal con cantidad restante
                                distributions.append({
                                    'warehouse': almacen,
                                    'quantity': restante,
                                    'is_principal': True
                                })
                                
                            else:
                                # Almacenes secundarios
                                distributions.append({
                                    'warehouse': almacen,
                                    'quantity': valorPerAlmacen,
                                    'is_principal': False
                                })
                        
                        if distributions:
                            self._create_crossdock_picking(line, distributions)


                        
                        


            if not (setuAdvanceReordering and moduloReglasAbastecimiento and line.product_id.warehouse_group_id):
                

                warehouses = self.env['stock.warehouse'].search([
                    ('company_id', '=', self.company_id.id)
                ], order='sequence')

                if not warehouses:
                    self.message_post(body=f"⚠️ No se encontraron almacenes para el producto <b>{line.product_id.display_name}</b>.")
                    continue

                almacenes_secundarios = warehouses.filtered(lambda w: w.lot_stock_id.id != self.picking_type_id.default_location_dest_id.id)
                almacen_principal = warehouses.filtered(lambda w: w.lot_stock_id.id == self.picking_type_id.default_location_dest_id.id)

                porcentaje = line.line_crossdock_percentage or (self.crossdock_percentage / 100)
                cantidad_total_crossdock = line.product_qty;

                cantidad_por_almacen = self.redondeo(
                    cantidad_total_crossdock / len(almacenes_secundarios),
                    line.distribution_multiple
                ) if almacenes_secundarios else 0


                

                # Preparar lista de distribuciones
                distributions = []

                # Asignar cantidades a almacenes secundarios
                for wh in almacenes_secundarios:
                    distributions.append({
                        'warehouse': wh,
                        'quantity': cantidad_por_almacen,
                        'is_principal': False
                    })


                # Crear picking y movimientos con el mismo método del resto del código
                if distributions:
                    self._create_crossdock_picking(line, distributions)
                
