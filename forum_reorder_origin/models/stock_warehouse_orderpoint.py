# -*- coding: utf-8 -*-
import math

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round

from odoo.addons.primate_reposicion_avanzada.models.distribution_strategy_mixin import (
    DISTRIBUTION_STRATEGIES,
)


class StockWarehouseOrderpoint(models.Model):
    _inherit = 'stock.warehouse.orderpoint'

    origin_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Almacén Origen',
        compute='_compute_origin_warehouse_id',
        store=True,
    )
    origin_qty_on_hand = fields.Float(
        string='[Origen] A la mano',
        compute='_compute_origin_quantities',
        digits='Product Unit of Measure',
    )
    origin_qty_available = fields.Float(
        string='[Origen] Disponible',
        compute='_compute_origin_quantities',
        digits='Product Unit of Measure',
    )
    origin_qty_forecast = fields.Float(
        string='[Origen] Pronosticado',
        compute='_compute_origin_quantities',
        digits='Product Unit of Measure',
    )
    origin_stock_warning = fields.Boolean(
        string='Alerta Stock Origen',
        compute='_compute_origin_stock_warning',
        search='_search_origin_stock_warning',
    )
    origin_qty_shortfall = fields.Float(
        string='[Origen] Faltante',
        readonly=True,
        copy=False,
        default=0.0,
        digits='Product Unit of Measure',
        help='Parte que le toca a esta regla del faltante de su grupo, donde el grupo son '
             'todas las reglas del mismo producto que salen del mismo almacén origen. Se '
             'reparte a prorrata de lo que pide cada regla, así que la suma de la columna es '
             'el faltante real del grupo y no el mismo stock contado una vez por fila.\n'
             'Se almacena para que la lista pueda totalizarlo: las cantidades de stock en '
             'origen, al ser computadas sin almacenar, no las puede agregar read_group.\n'
             'Muestra el último valor calculado: se escribe al correr "Recalcular Faltante" '
             'o al aplicar una distribución, no en cada cambio de stock.',
    )

    # ------------------------------------------------------------------
    # Distribución del stock insuficiente: la decisión se puede rehacer
    # ------------------------------------------------------------------
    # El wizard de distribución escribe el reparto en qty_to_order. Sin guardar la demanda
    # previa, ese reparto hace que el grupo entre en el stock disponible, el faltante pase a
    # cero y con eso desaparezcan la alerta y el botón: el usuario quedaba sin forma de
    # cambiar el criterio que acababa de aplicar. La foto de abajo es lo que permite volver
    # a repartir cuantas veces se quiera hasta que se ordene de verdad.

    forum_demand_original = fields.Float(
        string='Demanda Original',
        readonly=True,
        copy=False,
        default=0.0,
        digits='Product Unit of Measure',
        help='Cantidad que pedía la regla antes del primer reparto del ciclo actual. '
             'En cero significa que no hay ninguna distribución aplicada. Se limpia al '
             'ordenar la regla o al restaurar la demanda original.',
    )
    forum_demand_effective = fields.Float(
        string='Demanda a Considerar',
        compute='_compute_forum_demand_effective',
        store=True,
        digits='Product Unit of Measure',
        help='La demanda original mientras haya un reparto aplicado, y la cantidad a pedir '
             'actual en cualquier otro caso. Es la que se usa para agrupar y calcular el '
             'faltante, para que un reparto ya aplicado no oculte que el stock no alcanzaba.',
    )
    forum_distribution_strategy = fields.Selection(
        selection=DISTRIBUTION_STRATEGIES,
        string='Criterio Aplicado',
        readonly=True,
        copy=False,
        help='Último criterio con el que se repartió el stock insuficiente de esta regla. '
             'Se puede volver a aplicar otro distinto hasta que la regla se ordene.',
    )
    forum_distribution_date = fields.Datetime(
        string='Fecha del Reparto',
        readonly=True,
        copy=False,
    )

    @api.depends('qty_to_order', 'forum_demand_original')
    def _compute_forum_demand_effective(self):
        """La demanda original manda mientras haya un reparto vigente.

        Depende solo del propio registro, así que es barato incluso en las ~126k reglas
        candidatas: no hay agrupación ni lectura de hermanos como en el faltante.

        Si el usuario edita la cantidad a mano después de repartir, la base de comparación
        sigue siendo la original a propósito: es la que dice cuánto se necesitaba de verdad.
        Para mover esa base está "Restaurar Demanda Original".
        """
        for op in self:
            op.forum_demand_effective = (
                op.forum_demand_original if op.forum_demand_original > 0 else op.qty_to_order
            )

    @api.model_create_multi
    def create(self, vals_list):
        product_ids = {vals['product_id'] for vals in vals_list if vals.get('product_id')}
        if product_ids:
            multiples = {
                p.id: p.product_tmpl_id.mutiplos_distribucion
                for p in self.env['product.product'].browse(product_ids)
            }
            for vals in vals_list:
                multiple = multiples.get(vals.get('product_id'), 0)
                if multiple and multiple > 1:
                    vals['qty_multiple'] = float(multiple)
        return super().create(vals_list)

    @api.depends('route_id', 'route_id.supplier_wh_id', 'warehouse_id', 'warehouse_id.resupply_wh_ids')
    def _compute_origin_warehouse_id(self):
        for op in self:
            origin_wh = False
            if op.route_id and op.route_id.supplier_wh_id:
                origin_wh = op.route_id.supplier_wh_id
            elif op.warehouse_id and op.warehouse_id.resupply_wh_ids:
                origin_wh = op.warehouse_id.resupply_wh_ids[0]
            op.origin_warehouse_id = origin_wh

    @api.depends('product_id', 'origin_warehouse_id')
    def _compute_origin_quantities(self):
        for op in self:
            if op.product_id and op.origin_warehouse_id:
                product = op.product_id.with_context(
                    warehouse=op.origin_warehouse_id.id,
                    location=op.origin_warehouse_id.lot_stock_id.id,
                )
                op.origin_qty_on_hand = product.qty_available
                op.origin_qty_available = product.free_qty
                op.origin_qty_forecast = product.virtual_available
            else:
                op.origin_qty_on_hand = 0.0
                op.origin_qty_available = 0.0
                op.origin_qty_forecast = 0.0

    # ------------------------------------------------------------------
    # Agrupación por (producto, almacén origen)
    # ------------------------------------------------------------------

    # Campo de demanda por defecto para agrupar. Es la efectiva y no qty_to_order a
    # propósito: una regla que ya recibió un reparto y quedó en cero tiene que seguir
    # apareciendo en su grupo, o el usuario no puede rehacer la distribución.
    DEMAND_FIELD = 'forum_demand_effective'

    @api.model
    def _origin_candidate_domain(self, demand_field=None):
        """Reglas que compiten por stock de un almacén origen."""
        return [('origin_warehouse_id', '!=', False),
                (demand_field or self.DEMAND_FIELD, '>', 0)]

    @api.model
    def _origin_group_demands(self, restrict_to=None, demand_field=None):
        """Demanda y disponible por (producto, almacén origen), con read_group.

        Corazón de la corrección del bug: dos reglas del mismo producto que salen del mismo
        almacén origen compiten por el MISMO stock, así que hay que sumar la demanda del
        grupo y comparar esa suma contra el disponible, no cada regla por separado. Antes, 10
        reglas de 10 unidades con 90 disponibles pasaban todas la prueba individual
        (90 >= 10) y ninguna se marcaba, cuando entre las 10 piden 100.

        origin_qty_available se calcula por (producto, almacén origen), así que el disponible
        del grupo es un único valor y no se suma.

        Se usa read_group en vez de recorrer los registros: hay ~126k reglas candidatas y
        agruparlas en Python (uniendo recordsets dentro de un loop) es cuadrático. Acá la
        demanda de todos los grupos sale en una sola consulta, y el free_qty se pide una vez
        por almacén para todos sus productos.

        :param demand_field: qué cantidad se suma como demanda del grupo. Por defecto la
            efectiva (DEMAND_FIELD), que ignora un reparto ya aplicado y vuelve a la demanda
            original. Con 'qty_to_order' se agrupa por lo que las reglas piden HOY, que es lo
            que necesita la validación bloqueante de _check_origin_stock.
        :return: dict {(product_id, warehouse_id): {'demand': float, 'available': float,
                                                    'shortfall': float}}
        """
        from collections import defaultdict

        demand_field = demand_field or self.DEMAND_FIELD
        domain = self._origin_candidate_domain(demand_field=demand_field)
        if restrict_to is not None:
            productos = restrict_to.mapped('product_id').ids
            almacenes = restrict_to.mapped('origin_warehouse_id').ids
            if not productos or not almacenes:
                return {}
            domain = domain + [('product_id', 'in', productos),
                               ('origin_warehouse_id', 'in', almacenes)]

        agrupado = self.read_group(
            domain,
            fields=['%s:sum' % demand_field],
            groupby=['product_id', 'origin_warehouse_id'],
            lazy=False,
        )
        if not agrupado:
            return {}

        # Productos por almacén origen, para pedir el free_qty de una sola vez por almacén.
        productos_por_almacen = defaultdict(list)
        for fila in agrupado:
            product_id = fila['product_id'][0]
            warehouse_id = fila['origin_warehouse_id'][0]
            productos_por_almacen[warehouse_id].append(product_id)

        disponible = {}
        product_obj = self.env['product.product']
        warehouse_obj = self.env['stock.warehouse']
        for warehouse_id, product_ids in productos_por_almacen.items():
            almacen = warehouse_obj.browse(warehouse_id)
            productos = product_obj.browse(product_ids).with_context(
                warehouse=warehouse_id, location=almacen.lot_stock_id.id)
            for producto in productos:
                disponible[(producto.id, warehouse_id)] = producto.free_qty

        grupos = {}
        for fila in agrupado:
            clave = (fila['product_id'][0], fila['origin_warehouse_id'][0])
            demanda = fila[demand_field] or 0.0
            libre = disponible.get(clave, 0.0)
            grupos[clave] = {
                'demand': demanda,
                'available': libre,
                'shortfall': max(demanda - libre, 0.0),
            }
        return grupos

    @api.model
    def _group_candidates_by_origin(self, restrict_to=None, only_shortfall=False,
                                    demand_field=None):
        """Ídem _origin_group_demands, más el recordset de reglas de cada grupo.

        Instanciar los recordsets es lo caro, así que con only_shortfall=True solo se buscan
        las reglas de los grupos que efectivamente tienen faltante — que es lo que necesitan
        el marcado, el wizard y el cálculo del faltante.
        """
        demand_field = demand_field or self.DEMAND_FIELD
        grupos = self._origin_group_demands(restrict_to=restrict_to,
                                            demand_field=demand_field)
        if only_shortfall:
            grupos = {k: v for k, v in grupos.items() if v['shortfall'] > 0}
        if not grupos:
            return {}

        domain = self._origin_candidate_domain(demand_field=demand_field) + [
            ('product_id', 'in', [k[0] for k in grupos]),
            ('origin_warehouse_id', 'in', [k[1] for k in grupos]),
        ]
        candidatos = self.search(domain)
        por_clave = {}
        for op in candidatos:
            clave = (op.product_id.id, op.origin_warehouse_id.id)
            if clave in grupos:
                por_clave.setdefault(clave, []).append(op.id)

        resultado = {}
        for clave, datos in grupos.items():
            ids = por_clave.get(clave)
            if not ids:
                continue
            resultado[clave] = dict(datos, orderpoints=self.browse(ids))
        return resultado

    @api.model
    def _origin_unfulfillable_ids(self, restrict_to=None):
        """Ids de las reglas cuyo grupo no alcanza a cubrirse con el stock del origen.

        Si el grupo no alcanza, se marcan TODAS sus reglas: el faltante es del conjunto, no
        de una fila en particular.
        """
        grupos = self._group_candidates_by_origin(restrict_to=restrict_to,
                                                  only_shortfall=True)
        ids = set()
        for datos in grupos.values():
            ids.update(datos['orderpoints'].ids)
        return ids

    @api.depends('origin_qty_available', 'qty_to_order', 'forum_demand_effective',
                 'origin_warehouse_id', 'product_id')
    def _compute_origin_stock_warning(self):
        """Marca la regla si su GRUPO no se puede cumplir, no si ella sola no entra.

        El compute mira registros hermanos fuera de self, así que el agrupador busca todos
        los candidatos y no solo los de self; los @api.depends alcanzan para disparar el
        recálculo, pero no para delimitar qué se lee.
        """
        con_warning = self._origin_unfulfillable_ids(restrict_to=self) if self else set()
        for op in self:
            op.origin_stock_warning = op.id in con_warning

    def _search_origin_stock_warning(self, operator, value):
        """Filtro que usa exactamente el mismo criterio de agrupación que el campo."""
        con_warning = self._origin_unfulfillable_ids()
        if operator == '=' and value:
            return [('id', 'in', list(con_warning))]
        return [('id', 'not in', list(con_warning))]

    @api.model
    def _prorratear_faltante(self, orderpoints, faltante_grupo, demanda_grupo,
                             demand_field=None):
        """Reparte el faltante del grupo entre sus reglas, en pasos enteros de la UoM.

        Método del resto mayor: se trunca la parte proporcional de cada regla al paso de su
        unidad de medida, y el sobrante se reparte de a un paso entre las reglas con mayor
        resto. Garantiza las dos cosas a la vez: ninguna fila con decimales espurios, y suma
        exactamente igual al faltante del grupo.

        Desempate por id de la regla, para que el resultado sea reproducible.

        :return: dict {orderpoint: faltante asignado}
        """
        demand_field = demand_field or self.DEMAND_FIELD
        paso = orderpoints[0].product_uom.rounding or 1.0
        asignado, restos = {}, []
        for op in orderpoints:
            proporcion = faltante_grupo * (op[demand_field] / demanda_grupo)
            pasos = math.floor(float_round(proporcion / paso, precision_digits=6))
            base = pasos * paso
            asignado[op] = base
            restos.append((proporcion - base, op.id, op))

        # Sobrante por el truncado, en cantidad de pasos.
        sobrante = faltante_grupo - sum(asignado.values())
        pasos_sobrantes = int(round(sobrante / paso)) if paso else 0
        for _resto, _id, op in sorted(restos, key=lambda x: (-x[0], x[1]))[:pasos_sobrantes]:
            asignado[op] += paso
        return asignado

    @api.model
    def _write_origin_qty_shortfall(self, restrict_to=None):
        """Escribe el faltante en origen de cada regla candidata.

        No es un campo computado: con 125.831 reglas candidatas, un stored compute con
        depends obliga a Odoo a calcularlo para todas al instalar y a rehacer la agrupación
        por cada lote. Se escribe explícitamente, y la columna muestra el último valor
        calculado.

        El faltante del grupo se reparte a prorrata de lo que pide cada regla, así la suma de
        la columna da el faltante real y no el mismo stock contado una vez por fila.

        El reparto se hace en unidades enteras (en realidad, en pasos de la precisión de la
        unidad de medida del producto: 1 para "Unidades"). No alcanza con redondear cada fila
        por separado: 5 unidades faltantes entre 33 reglas dan 0,1515 cada una, que redondeado
        da 0 en todas y la columna totalizaría 0 en vez de 5. Se usa reparto por resto mayor:
        se trunca cada fila al paso y las unidades sobrantes se asignan de a una a las filas
        con mayor resto. Así cada fila queda entera y la suma es exacta.
        """
        grupos = self._group_candidates_by_origin(restrict_to=restrict_to,
                                                  only_shortfall=True)
        por_valor = {}
        alcanzadas = self.env['stock.warehouse.orderpoint']
        for datos in grupos.values():
            alcanzadas |= datos['orderpoints']
            if not datos['shortfall'] or not datos['demand']:
                continue
            for op, valor in self._prorratear_faltante(
                    datos['orderpoints'], datos['shortfall'], datos['demand']).items():
                por_valor.setdefault(valor, self.env['stock.warehouse.orderpoint'])
                por_valor[valor] |= op

        for valor, ops in por_valor.items():
            ops.write({'origin_qty_shortfall': valor})

        # El resto de las candidatas se pone en CERO, no se deja sin escribir. Dos razones:
        #   - borrar valores viejos de un recálculo anterior;
        #   - y sobre todo, que la columna no quede en NULL. read_group ignora los NULL, así
        #     que un grupo donde todas las filas están en NULL devuelve False y la lista
        #     agrupada muestra la celda en blanco en vez de un total. Con ceros explícitos el
        #     total suma bien.
        # Se escribe siempre, sin filtrar por el valor actual: un NULL se lee como 0.0 desde
        # el ORM, así que filtrar por "distinto de cero" dejaba los NULL sin tocar — que era
        # exactamente el bug.
        campo = self.DEMAND_FIELD
        candidatas = self.search(self._origin_candidate_domain()) if restrict_to is None \
            else restrict_to.filtered(lambda o: o.origin_warehouse_id and o[campo] > 0)
        con_faltante = self.env['stock.warehouse.orderpoint'].union(*por_valor.values()) \
            if por_valor else self.env['stock.warehouse.orderpoint']
        en_cero = candidatas - con_faltante
        if en_cero:
            en_cero.write({'origin_qty_shortfall': 0.0})
        return candidatas | con_faltante

    @api.model
    def action_recompute_origin_shortfall(self):
        """Fuerza el recálculo del faltante en todas las reglas candidatas.

        Hace falta porque el faltante depende del stock del origen, y no hay dependencia que
        Odoo pueda seguir para free_qty con contexto de almacén: si el stock se mueve, el
        valor almacenado queda viejo hasta que algo lo dispare. Tampoco se recalculan las
        reglas hermanas cuando se edita el qty_to_order de una sola.
        """
        candidatos = self._write_origin_qty_shortfall()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Faltante recalculado'),
                'message': _('Se recalculó el faltante en origen de %s reglas.') % len(candidatos),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_open_product(self):
        """Abre la ficha del producto de la regla.

        Existe porque setu_advance_reordering pone edit="0" en el árbol de reabastecimiento
        (views/stock_warehouse_orderpoint.xml:114). Con la lista en solo lectura, la celda de
        product_id nunca entra en modo edición y por lo tanto no aparece la flecha de enlace
        interno con la que se llegaba al producto. Este botón recupera la navegación sin
        re-habilitar la edición en línea, que el vendor deshabilitó a propósito.
        """
        self.ensure_one()
        return {
            'name': self.product_id.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'product.product',
            'res_id': self.product_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # Ciclo de vida de la foto de la demanda
    # ------------------------------------------------------------------

    def forum_snapshot_demand(self, strategy=None):
        """Guarda la demanda actual como original, si todavía no hay una foto tomada.

        Se llama desde el wizard de distribución antes de escribir el reparto. La foto se
        toma UNA sola vez por ciclo: si el usuario aplica un segundo criterio, la original
        que se conserva es la de antes del primer reparto, no la ya recortada. Sin eso, cada
        reparto sucesivo achicaría la base y el segundo criterio repartiría sobre migas del
        primero en lugar de sobre la necesidad real.
        """
        ahora = fields.Datetime.now()
        for op in self:
            vals = {'forum_distribution_date': ahora}
            if strategy:
                vals['forum_distribution_strategy'] = strategy
            if op.forum_demand_original <= 0:
                vals['forum_demand_original'] = op.qty_to_order
            op.write(vals)
        return True

    def forum_clear_distribution(self):
        """Cierra el ciclo: sin foto, la demanda efectiva vuelve a ser la cantidad a pedir."""
        return self.write({
            'forum_demand_original': 0.0,
            'forum_distribution_strategy': False,
            'forum_distribution_date': False,
        })

    def action_restore_original_demand(self):
        """Deshace el reparto: devuelve la cantidad a pedir a su valor original.

        Es la salida para el caso "me equivoqué y quiero volver al punto de partida", sin
        tener que acordarse de qué pedía cada regla antes de repartir.
        """
        con_foto = self.filtered(lambda o: o.forum_demand_original > 0)
        if not con_foto:
            raise UserError(_(
                'Ninguna de las reglas seleccionadas tiene un reparto aplicado, así que no '
                'hay demanda original que restaurar.'))
        for op in con_foto:
            op.qty_to_order = op.forum_demand_original
        con_foto.forum_clear_distribution()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Demanda original restaurada'),
                'message': _('Se devolvió la cantidad a pedir original en %s regla(s). '
                             'Podés volver a distribuir con otro criterio.') % len(con_foto),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_replenish(self, force_to_max=False):
        """Override para validar stock en origen antes de reabastecer."""
        unfulfillable = self._check_origin_stock()
        if unfulfillable:
            self._raise_origin_stock_error(unfulfillable)
        res = super().action_replenish(force_to_max=force_to_max)
        # Acá la decisión se efectivizó: el movimiento ya se generó, así que el ciclo de
        # distribución se cierra y la foto se descarta. exists() porque el action_replenish
        # del core borra las reglas manuales que quedan en cero.
        self.exists().forum_clear_distribution()
        return res

    def action_replenish_auto(self):
        """Override para validar stock en origen antes de automatizar."""
        unfulfillable = self._check_origin_stock()
        if unfulfillable:
            self._raise_origin_stock_error(unfulfillable)
        res = super().action_replenish_auto()
        self.exists().forum_clear_distribution()
        return res

    def action_open_origin_warning_wizard(self):
        """Abre wizard de confirmación para forzar reabastecimiento con stock insuficiente."""
        unfulfillable = self._check_origin_stock()
        message = self._build_warning_message(unfulfillable) if unfulfillable else _(
            "No hay reglas con stock insuficiente en origen en la selección actual."
        )
        wizard = self.env['forum.reorder.warning.wizard'].create({
            'message': message,
            'orderpoint_ids': [(6, 0, self.ids)],
            'has_unfulfillable': bool(unfulfillable),
        })
        return {
            'name': _('Alerta de Stock en Origen'),
            'type': 'ir.actions.act_window',
            'res_model': 'forum.reorder.warning.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
            'views': [(False, 'form')],
        }

    def _check_origin_stock(self):
        """Retorna las reglas de self cuyo GRUPO no se puede cumplir.

        Usa el mismo agrupador que el campo de alerta y el filtro, pero agrupando por
        qty_to_order y NO por la demanda efectiva. La diferencia es deliberada:

        - la alerta y el botón de distribución miran la demanda ORIGINAL, para que un reparto
          ya aplicado no borre la evidencia de que el stock no alcanzaba y el usuario pueda
          cambiar de criterio;
        - esta validación mira lo que las reglas piden HOY, porque es lo que se va a mover de
          verdad. Si mirara la original, una vez repartido el stock la regla quedaría
          bloqueada para siempre: la demanda original nunca entra en el disponible, es
          justamente la definición del faltante.

        El detalle informa la demanda del grupo, no la de la fila: es la que efectivamente no
        entra en el stock del origen.
        """
        unfulfillable = []
        grupos = self._group_candidates_by_origin(restrict_to=self, only_shortfall=True,
                                                  demand_field='qty_to_order')
        for (product_id, warehouse_id), datos in grupos.items():
            rounding = datos['orderpoints'][0].product_uom.rounding
            if float_compare(datos['available'], datos['demand'],
                             precision_rounding=rounding) >= 0:
                continue
            for op in datos['orderpoints'] & self:
                unfulfillable.append({
                    'orderpoint_id': op.id,
                    'product': op.product_id.display_name,
                    'location': op.location_id.display_name,
                    'origin_warehouse': op.origin_warehouse_id.display_name,
                    'available': datos['available'],
                    'requested': op.qty_to_order,
                    'group_requested': datos['demand'],
                    'group_count': len(datos['orderpoints']),
                })
        return unfulfillable

    def _build_warning_message(self, unfulfillable):
        detail_lines = []
        for item in unfulfillable:
            detail_lines.append(
                f"• {item['product']} en {item['location']}: "
                f"disponible en {item['origin_warehouse']} = {item['available']}, "
                f"esta regla pide {item['requested']} y las "
                f"{item['group_count']} reglas del mismo origen piden "
                f"{item['group_requested']} en total"
            )
        return _(
            "Stock insuficiente en origen para las siguientes reglas:\n\n%s"
        ) % '\n'.join(detail_lines)

    def _raise_origin_stock_error(self, unfulfillable):
        message = self._build_warning_message(unfulfillable)
        raise UserError(message)
