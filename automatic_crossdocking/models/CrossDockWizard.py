from odoo import models, fields, api
from odoo.exceptions import ValidationError
import math;


import logging;

_logger = logging.getLogger(__name__);


class CrossdockDistributionLineWizard(models.TransientModel):
    _name = 'crossdock.distribution.line.wizard'
    _description = 'Línea de distribución en Crossdock Wizard'

    wizard_id = fields.Many2one('crossdock.distribution.wizard', string='Wizard padre', required=True, ondelete='cascade')
    product = fields.Many2one('product.product', string="Producto");
    almacenPrincipal = fields.Many2one('stock.warehouse', string="Almacén Principal");
    cantidadAlmacenPrincipal = fields.Float(string="Cantidad Asignada", required=True);
    cantidadAlmacenesSecundarios = fields.Float(string="Cantidad asignada hacia cada almacén secundarios", required=True)

class CrossdockDistributionWizard(models.TransientModel):
    _name = 'crossdock.distribution.wizard'
    _description = 'Edición de distribución de Crossdock'

    purchase_id = fields.Many2one('purchase.order', string="Orden de Compra", required=True)
    line_ids = fields.One2many('crossdock.distribution.line.wizard', 'wizard_id', string="Distribución");

    def redondeo(self, val, multiplo, method):

        if method == 'nearest':
            return round(val * multiplo);

        elif method == 'floor':
            return math.floor(val * multiplo);

        else:
            return math.ceil(val * multiplo);

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields);

        setuAdvanceReordering = self.env['ir.module.module'].sudo().search([
                ('name', '=', 'setu_advance_reordering'),
                ('state', '=', 'installed')
            ], limit=1)

        moduloReglasAbastecimiento = self.env['ir.module.module'].sudo().search([
                ('name', '=', 'automatizacion_reglas_abastecimiento'),
                ('state', '=', 'installed')
            ], limit=1);
        
        if not setuAdvanceReordering or not moduloReglasAbastecimiento:
            raise ValidationError("Los módulos necesarios no se encuentran instalados, se hará una distribución equitativa entre los almacenes secundarios.");
        
        purchase_id = self._context.get('default_purchase_order_id') or self._context.get('active_id')
        
        if not purchase_id:
            return res
        
        res['purchase_id'] = purchase_id
        
        purchase = self.env['purchase.order'].browse(purchase_id)
        if not purchase.exists():
            return res
        
        valores = [];
        
        almacenes = self.env['stock.warehouse'].search([])
        
        for line in purchase.order_line.filtered('use_crossdock'):
            
            cantidad = line.product_qty;
            producto = line.product_id;

            if not line.product_id.warehouse_group_id:
                raise ValidationError("La variante no cuenta con grupos asignados");




            porcentaje  = 0;
            if line.line_crossdock_percentage:
                porcentaje = line.line_crossdock_percentage;
            else:
                porcentaje = purchase.crossdock_percentage / 100;
    
            if not porcentaje:
                raise ValidationError("No existe un porcentaje asignado, no se pueden hacer los cálculos");
        

            cantidadAlmacenes = len(almacenes);
            almacenPrincipal = None;
            for almacen in almacenes:
                if almacen.id == 1:
                    cantidadAlmacenes -= 1;
                    almacenPrincipal = almacen;

            if cantidadAlmacenes == 0:
                cantidadAlmacenes = 1;
            
            

            if not line.distribution_multiple:
                raise ValueError("El número para distribución multiplo no es valido");
            


            cantidadPorcentaje = line.product_qty * porcentaje;

            restante = round(line.product_qty - cantidadPorcentaje);
            method = purchase.distribution_rounding_method or 'nearest'

            valorPerAlmacen = self.redondeo(cantidadPorcentaje / cantidadAlmacenes, line.distribution_multiple, method);

            categoriaProducto = producto.categ_id;

            grupo = producto.warehouse_group_id;


            for cat in grupo.category_rule_ids:
                if categoriaProducto.id == cat.id:
                    if line.product_qty > cat.max_qty or line.product_qty < cat.min_qty:
                        raise ValidationError(f"Las cantidades deben estar dentro del rango {cat.min_qty} - {cat.max_qty}")
            

            valores.append((0,0, {
                'product': line.product_id.id,
                'cantidadAlmacenPrincipal': restante,
                'cantidadAlmacenesSecundarios': valorPerAlmacen,
                'almacenPrincipal': almacenPrincipal
            }))

            # for almacen in almacenes:

            #     valores.append((0,0))


            #     if almacen.id == 1 and len(almacenes) == 1:
            #             valores.append((0, 0, {
            #                 'product': line.product_id.id,
            #                 'almacen': almacen.id,
            #                 'cantidadAsignada': line.product_qty,
            #                 'almacenPrincipal': almacenPrincipal.id,
            #             }))


            #     elif almacen.id == 1:
            #             valores.append((0, 0, {
            #                 'product': line.product_id.id,
            #                 'almacen': almacen.id,
            #                 'cantidadAsignada': restante,
            #                 'almacenPrincipal': almacenPrincipal.id,
            #             }))
                        
            #     else:

            #             valores.append((0, 0, {
            #                 'product': line.product_id.id,
            #                 'almacen': almacen.id,
            #                 'cantidadAsignada': valorPerAlmacen,
            #                 'almacenPrincipal': almacenPrincipal.id,
            #             }))

        res['line_ids'] = valores;
        
        return res;


    def editarInformacion(self):
        self.ensure_one()

        total_general = sum(
            l.cantidadAlmacenPrincipal + l.cantidadAlmacenesSecundarios
            for l in self.line_ids
        )

        for line in self.line_ids:
            # Línea original de la OC
            po_line = self.purchase_id.order_line.filtered(
                lambda l: l.product_id == line.product and l.use_crossdock
            )
            if not po_line:
                raise ValidationError(f"No se encontró la línea de OC para {line.product.display_name}")

            cantidad_total = po_line.product_qty
            suma_asignada = line.cantidadAlmacenPrincipal + line.cantidadAlmacenesSecundarios

            # ❌ No exceder cantidad
            if suma_asignada > cantidad_total:
                raise ValidationError(
                    f"La suma asignada para {line.product.display_name} excede la cantidad total ({cantidad_total})."
                )

            # ❌ No permitir cantidades negativas
            if line.cantidadAlmacenPrincipal < 0 or line.cantidadAlmacenesSecundarios < 0:
                raise ValidationError(
                    f"No puedes asignar cantidades negativas para {line.product.display_name}"
                )

            # ❌ Validar múltiplos
            if po_line.distribution_multiple:
                if (line.cantidadAlmacenPrincipal % po_line.distribution_multiple != 0 or
                    line.cantidadAlmacenesSecundarios % po_line.distribution_multiple != 0):
                    raise ValidationError(
                        f"Las cantidades para {line.product.display_name} no respetan el múltiplo {po_line.distribution_multiple}."
                    )

            # 🔹 Repartir la cantidad de almacenes secundarios según reglas
            almacenes_secundarios = self.env['stock.warehouse'].search([
                ('id', '!=', 1)
            ]);

            purchase_id = self._context.get('default_purchase_order_id') or self._context.get('active_id')
            
            purchase = self.env['purchase.order'].browse(purchase_id);

            cantidadAlmacenesSec = line.cantidadAlmacenesSecundarios * len(almacenes_secundarios)
            porcentaje = None;
            for linea in purchase.order_line:
                


                if linea.product_id == line.product:

                    porcentaje = (cantidadAlmacenesSec / linea.product_qty);
                    
                    linea.sudo().write({
                        'line_crossdock_percentage': porcentaje,
                    })


            picking = self.env['stock.picking'].search([
                ('origin', '=', f'Crossdock {purchase.name}')
            ])

            for pick in picking:

                for mov in pick.move_ids:

                    warehouse_dest = self.env['stock.warehouse'].search([
                        ('lot_stock_id', '=', mov.location_dest_id.id)
                    ], limit=1)


                    if mov.product_id.id == line.product.id:
                        if warehouse_dest and warehouse_dest.id == 1:
                            mov.sudo().write({
                                'product_uom_qty': line.cantidadAlmacenPrincipal
                            })
                        elif warehouse_dest and warehouse_dest.id != 1:
                            
                            mov.sudo().write({
                                'product_uom_qty': line.cantidadAlmacenesSecundarios
                            })

            