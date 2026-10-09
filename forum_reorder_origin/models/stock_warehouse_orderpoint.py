# -*- coding: utf-8 -*-
import logging
import math
import time

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.osv import expression
from odoo.tools import float_compare, float_round

from odoo.addons.primate_reposicion_avanzada.models.distribution_strategy_mixin import (
    DISTRIBUTION_STRATEGIES,
)

_logger = logging.getLogger(__name__)

# Última regeneración del informe de reabastecimiento, por (base, compañía). Vive en memoria
# del proceso a propósito: guardarla en ir.config_parameter invalidaría las cachés de todos
# los workers en cada apertura de la pantalla. Cada worker regenera, como mucho, una vez por
# ventana.
_REPORTE_ULTIMO = {}

# Clave de la caché por transacción del conjunto de reglas no cumplibles.
CACHE_NO_CUMPLIBLES = 'forum_reorder_origin.no_cumplibles'


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

    forum_sin_ruta = fields.Boolean(
        string='Sin ruta de abastecimiento',
        compute='_compute_forum_sin_ruta',
        search='_search_forum_sin_ruta',
        help='No hay ninguna regla de abastecimiento que llegue a esta ubicación por las rutas '
             'del producto, su categoría, el almacén o la propia regla. Al ordenarla falla con '
             '«No se encontró regla para abastecer».',
    )
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
        self._limpiar_cache_no_cumplibles()
        return super().create(vals_list)

    def write(self, vals):
        self._limpiar_cache_no_cumplibles()
        return super().write(vals)

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

        # _read_group y no read_group: el público formatea cada grupo para la pantalla y arma
        # el nombre visible de cada producto (≈ 27 mil, 10 s de los 13 que tardaba el filtro
        # de cumplibles) que acá no se usa. Los ids de cada grupo salen en la misma consulta.
        agrupado = self._read_group(
            domain,
            groupby=['product_id', 'origin_warehouse_id'],
            aggregates=['%s:sum' % demand_field, 'id:array_agg'],
        )
        if not agrupado:
            return {}

        # Productos por almacén origen, para pedir el free_qty de una sola vez por almacén.
        productos_por_almacen = defaultdict(list)
        for producto, almacen, _demanda, _ids in agrupado:
            productos_por_almacen[almacen.id].append(producto.id)

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
        for producto, almacen, demanda, ids in agrupado:
            clave = (producto.id, almacen.id)
            demanda = demanda or 0.0
            libre = disponible.get(clave, 0.0)
            grupos[clave] = {
                'demand': demanda,
                'available': libre,
                'shortfall': max(demanda - libre, 0.0),
                '_ids': ids,
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

        # Los ids de cada grupo ya vienen del agrupado (array_agg): antes se volvían a buscar
        # todas las candidatas con un search_read que además formateaba los many2one.
        resultado = {}
        for clave, datos in grupos.items():
            datos = dict(datos)
            ids = datos.pop('_ids', None)
            if not ids:
                continue
            resultado[clave] = dict(datos, orderpoints=self.browse(sorted(ids)))
        return resultado

    @api.model
    def _ids_sin_ruta(self, ids=None):
        """Reglas activas para las que no hay NINGUNA regla de abastecimiento que llegue.

        Reproduce en SQL la búsqueda de `procurement.group._search_rule`: una regla de stock
        sirve si no es de empuje, está activa, su destino es la ubicación de la regla de
        reorden o un padre, su almacén es el mismo o ninguno, y pertenece a alguna ruta que
        aplica: la de la propia regla de reorden, las del producto, las de su categoría (con
        las de las categorías padre) o las del almacén. Si no hay ninguna, «Ordenar» falla
        con «No se encontró regla para abastecer…».

        Es un control, no un sustituto de la búsqueda real: no mira paquetes ni rutas por
        empaque, que Forum no usa.
        """
        filtro = "AND o.id IN %s" if ids is not None else ""
        if ids is not None and not ids:
            return set()
        self.env.flush_all()
        self.env.cr.execute(f"""
            SELECT o.id
              FROM stock_warehouse_orderpoint o
              JOIN product_product pp ON pp.id = o.product_id
              JOIN product_template pt ON pt.id = pp.product_tmpl_id
              JOIN product_category pc ON pc.id = pt.categ_id
              JOIN stock_location l ON l.id = o.location_id
             WHERE o.active {filtro}
               AND NOT EXISTS (
                    SELECT 1
                      FROM stock_rule r
                      JOIN stock_location dl ON dl.id = r.location_dest_id
                      JOIN stock_route rt ON rt.id = r.route_id AND rt.active
                     WHERE r.active
                       AND r.action != 'push'
                       AND l.parent_path LIKE dl.parent_path || '%%'
                       AND (r.warehouse_id IS NULL OR r.warehouse_id = o.warehouse_id)
                       AND (r.company_id IS NULL OR r.company_id = o.company_id)
                       AND (r.route_id = o.route_id
                            OR r.route_id IN (SELECT rp.route_id FROM stock_route_product rp
                                               WHERE rp.product_id = pt.id)
                            OR r.route_id IN (SELECT rc.route_id FROM stock_route_categ rc
                                                JOIN product_category c ON c.id = rc.categ_id
                                               WHERE pc.parent_path LIKE c.parent_path || '%%')
                            OR r.route_id IN (SELECT rw.route_id FROM stock_route_warehouse rw
                                               WHERE rw.warehouse_id = o.warehouse_id))
               )
        """, [tuple(ids)] if ids is not None else [])
        return {fila[0] for fila in self.env.cr.fetchall()}

    def _compute_forum_sin_ruta(self):
        sin_ruta = self._ids_sin_ruta([i for i in self.ids if isinstance(i, int)])
        for op in self:
            op.forum_sin_ruta = op.id in sin_ruta

    def _search_forum_sin_ruta(self, operator, value):
        if operator not in ('=', '!='):
            raise UserError(_('Operación no soportada.'))
        positivo = (operator == '=') == bool(value)
        return [('id', 'in' if positivo else 'not in', list(self._ids_sin_ruta()))]

    def action_agregar_ruta_sucursal(self):
        """Agrega a cada producto la ruta que abastece la sucursal de la regla, si le falta.

        Es la corrección de «No se encontró regla para abastecer»: la ruta de la sucursal es
        la de reabastecimiento entre almacenes que Odoo marca con `supplied_wh_id`. Sólo
        AGREGA: no saca rutas ni toca reglas, así que no puede dejar a otra regla sin ruta.
        Las reglas cuya sucursal no tiene ruta de abastecimiento se informan.
        """
        sin_ruta = self.filtered('forum_sin_ruta')
        rutas = self.env['stock.route'].search([
            ('supplied_wh_id', 'in', sin_ruta.warehouse_id.ids),
            ('product_selectable', '=', True)])
        por_almacen = {}
        for ruta in rutas:
            por_almacen.setdefault(ruta.supplied_wh_id.id, self.env['stock.route'])
            por_almacen[ruta.supplied_wh_id.id] |= ruta
        agregar, sin_ruta_de_sucursal = {}, self.browse()
        for op in sin_ruta:
            ruta = por_almacen.get(op.warehouse_id.id)
            if not ruta:
                sin_ruta_de_sucursal |= op
                continue
            plantilla = op.product_id.product_tmpl_id
            agregar[plantilla] = agregar.get(plantilla, self.env['stock.route']) | ruta
        for plantilla, ruta in agregar.items():
            plantilla.write({'route_ids': [Command.link(r.id) for r in ruta]})
        # Campo calculado sin dependencias: lo ya leído en esta petición quedó viejo.
        self.invalidate_model(['forum_sin_ruta'])
        mensaje = _('Se agregó la ruta de sucursal a %s producto(s).') % len(agregar)
        if sin_ruta_de_sucursal:
            mensaje += '\n' + _('%s regla(s) quedan sin ruta: su sucursal no tiene ruta de '
                                 'abastecimiento (%s).') % (
                len(sin_ruta_de_sucursal),
                ', '.join(sin_ruta_de_sucursal.warehouse_id.mapped('name')))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Rutas de sucursal'),
                'message': mensaje,
                'type': 'warning' if sin_ruta_de_sucursal else 'success',
                'sticky': bool(sin_ruta_de_sucursal),
            },
        }

    @api.model
    def _origin_unfulfillable_ids_todas(self):
        """Las no cumplibles de TODAS las candidatas, calculadas una vez por transacción.

        La lista filtrada por «cumplibles» pide el mismo dominio varias veces en una sola
        petición (búsqueda, conteo, agrupaciones) y cada vez reagrupaba las 125 mil reglas
        candidatas. Dentro de una petición de lectura el stock no cambia; si la petición
        escribe reglas, la caché se descarta en create/write.
        """
        cache = self.env.cr.cache
        if CACHE_NO_CUMPLIBLES not in cache:
            cache[CACHE_NO_CUMPLIBLES] = frozenset(self._origin_unfulfillable_ids())
        return cache[CACHE_NO_CUMPLIBLES]

    @api.model
    def _limpiar_cache_no_cumplibles(self):
        self.env.cr.cache.pop(CACHE_NO_CUMPLIBLES, None)

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
        if not self:
            return
        # Si la petición ya calculó el conjunto completo (el filtro de la lista), se reusa.
        con_warning = self.env.cr.cache.get(CACHE_NO_CUMPLIBLES)
        if con_warning is None:
            con_warning = self._origin_unfulfillable_ids(restrict_to=self)
        for op in self:
            op.origin_stock_warning = op.id in con_warning

    def _search_origin_stock_warning(self, operator, value):
        """Filtro que usa exactamente el mismo criterio de agrupación que el campo."""
        con_warning = self._origin_unfulfillable_ids_todas()
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
        # Se acumulan IDS, no recordsets. Un `recordset |= registro` dentro del loop copia la
        # tupla entera de ids en cada vuelta: con 204.897 candidatas el recálculo pasaba de
        # 18 segundos a más de diez minutos sin terminar. Es el mismo error cuadrático que ya
        # se había corregido en el agrupador (ver 17.0.2.0.0); acá había vuelto por otra
        # puerta. Los recordsets se instancian una sola vez, al escribir.
        ids_por_valor = {}
        for datos in grupos.values():
            if not datos['shortfall'] or not datos['demand']:
                continue
            for op, valor in self._prorratear_faltante(
                    datos['orderpoints'], datos['shortfall'], datos['demand']).items():
                ids_por_valor.setdefault(valor, []).append(op.id)

        ids_con_faltante = set()
        for valor, ids in ids_por_valor.items():
            ids_con_faltante.update(ids)
            self.browse(ids).write({'origin_qty_shortfall': valor})

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
        ids_en_cero = [i for i in candidatas.ids if i not in ids_con_faltante]
        if ids_en_cero:
            self.browse(ids_en_cero).write({'origin_qty_shortfall': 0.0})
        return self.browse(set(candidatas.ids) | ids_con_faltante)

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
        """Override para validar stock en origen antes de reabastecer.

        Con más de una regla seleccionada, el reabastecimiento es TOLERANTE: una regla sin ruta
        (o con cualquier otro error de abastecimiento) no tira abajo las demás. El core ya sabe
        hacerlo —es lo que usa el planificador— con `raise_user_error=False`: aparta las
        reglas que fallan, procesa el resto y deja una actividad en la ficha del producto. La
        pantalla, en cambio, lo llama con el error activado, y una sola regla mala cancelaba
        el lote entero de miles. Las que fallan se informan al final en un aviso.

        Con una sola regla se mantiene el comportamiento del core: el error con el botón para
        ir a corregir el producto.
        """
        unfulfillable = self._check_origin_stock()
        if unfulfillable:
            self._raise_origin_stock_error(unfulfillable)
        if len(self) <= 1:
            res = super().action_replenish(force_to_max=force_to_max)
        else:
            errores = self.env.cr.cache.setdefault('forum_reposicion_errores', [])
            del errores[:]
            res = super(StockWarehouseOrderpoint, self.with_context(
                reposicion_tolerante=True,
                stock_proceso_masivo=True,
                wis_encolar_envios=True,
            )).action_replenish(force_to_max=force_to_max)
            if errores:
                res = self._notificacion_reposicion_parcial(errores)
            del errores[:]
        # Acá la decisión se efectivizó: el movimiento ya se generó, así que el ciclo de
        # distribución se cierra y la foto se descarta. exists() porque el action_replenish
        # del core borra las reglas manuales que quedan en cero.
        self.exists().forum_clear_distribution()
        return res

    def _procure_orderpoint_confirm(self, use_new_cursor=False, company_id=None,
                                    raise_user_error=True):
        if self.env.context.get('reposicion_tolerante'):
            raise_user_error = False
        return super()._procure_orderpoint_confirm(
            use_new_cursor=use_new_cursor, company_id=company_id,
            raise_user_error=raise_user_error)

    def _notificacion_reposicion_parcial(self, errores):
        """Aviso fijo con las reglas que no se pudieron reabastecer y por qué."""
        por_mensaje = {}
        for orderpoint, mensaje in errores:
            por_mensaje.setdefault(mensaje, self.browse())
            por_mensaje[mensaje] |= orderpoint
        fallidas = self.browse().concat(*por_mensaje.values())
        lineas = []
        for mensaje, reglas in list(por_mensaje.items())[:10]:
            nombres = ', '.join(reglas[:5].mapped(
                lambda o: '%s (%s)' % (o.product_id.display_name, o.warehouse_id.name)))
            if len(reglas) > 5:
                nombres += _(' y %s más') % (len(reglas) - 5)
            lineas.append('• %s: %s' % (mensaje.strip().splitlines()[0], nombres))
        _logger.warning("Reabastecimiento parcial: %s de %s reglas no se pudieron procesar.",
                        len(fallidas), len(self))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reabastecimiento parcial: %s de %s reglas no se procesaron')
                         % (len(fallidas), len(self)),
                'message': _('El resto se ordenó. Las reglas con error quedan en la lista '
                             '(filtro «Sin ruta de abastecimiento») y con una actividad en la '
                             'ficha del producto.\n\n%s') % '\n'.join(lineas),
                'type': 'warning',
                'sticky': True,
            },
        }

    @api.model
    def _get_orderpoint_action(self):
        """Regenera el informe de reabastecimiento como mucho una vez por ventana.

        El core lo recorre ENTERO cada vez que se abre la pantalla —y la pantalla se vuelve a
        abrir sola después de cada «Ordenar»—: lee el pronóstico de todos los productos con
        stock negativo y crea las reglas manuales que falten. Con el catálogo de Forum son
        ≈ 20 s por apertura. Dentro de la ventana (parámetro
        `forum_reorder_origin.reporte_minutos`, 10 por defecto; 0 la desactiva) se devuelve la
        acción sin regenerar: las reglas que ya existen se siguen viendo y actualizando.
        """
        minutos = int(self.env['ir.config_parameter'].sudo().get_param(
            'forum_reorder_origin.reporte_minutos', 10) or 0)
        clave = (self.env.cr.dbname, self.env.company.id)
        ahora = time.time()
        if minutos > 0 and not self.env.context.get('forum_reporte_forzar') \
                and ahora - _REPORTE_ULTIMO.get(clave, 0) < minutos * 60:
            action = self.env["ir.actions.actions"]._for_xml_id(
                "stock.action_orderpoint_replenish")
            action['context'] = self.env.context
            return action
        contexto = self.env.context
        self.env.cr.cache.pop('forum_reporte_reglas', None)
        try:
            res = super(StockWarehouseOrderpoint, self.with_context(
                forum_reporte_rapido=True))._get_orderpoint_action()
        finally:
            self.env.cr.cache.pop('forum_reporte_reglas', None)
        res['context'] = contexto
        _REPORTE_ULTIMO[clave] = ahora
        return res

    @api.model
    def _get_orderpoint_products(self):
        """Al regenerar el informe, sólo los productos que el core no va a descartar.

        El core cruza CADA producto con CADA ubicación de reposición (15 mil × 48 en Forum) y,
        en cada cruce, recorre todos los stocks y movimientos del producto para ver si el
        saldo da negativo; si no da negativo, lo descarta. Acá se calcula ese mismo saldo
        —mismas consultas, misma comparación por `parent_path`, mismo redondeo— de una sola
        pasada por las filas, y se le pasan al core sólo los productos con algún saldo
        negativo. El resultado del informe es el mismo; lo que se ahorra es el cruce.
        """
        productos = super()._get_orderpoint_products()
        if not self.env.context.get('forum_reporte_rapido') or not productos:
            return productos
        return self._forum_productos_con_saldo_negativo(productos)

    @api.model
    def _forum_productos_con_saldo_negativo(self, productos):
        from collections import defaultdict

        ubicaciones = self._get_orderpoint_locations()
        if not ubicaciones:
            return productos
        Move = self.env['stock.move'].with_context(active_test=False)
        Quant = self.env['stock.quant'].with_context(active_test=False)
        dominio_quant, dominio_entra, dominio_sale = productos._get_domain_locations_new(
            ubicaciones.ids)
        estados = [('state', 'in', ('waiting', 'confirmed', 'assigned', 'partially_available'))]
        de_productos = [('product_id', 'in', productos.ids)]
        filas = []
        for producto, ubicacion, cantidad in Quant._read_group(
                expression.AND([de_productos, dominio_quant]),
                ['product_id', 'location_id'], ['quantity:sum']):
            filas.append((producto.id, ubicacion, cantidad))
        for producto, ubicacion, cantidad in Move._read_group(
                expression.AND([de_productos, estados, dominio_entra]),
                ['product_id', 'location_dest_id'], ['product_qty:sum']):
            filas.append((producto.id, ubicacion, cantidad))
        for producto, ubicacion, cantidad in Move._read_group(
                expression.AND([de_productos, estados, dominio_sale]),
                ['product_id', 'location_id'], ['product_qty:sum']):
            filas.append((producto.id, ubicacion, -cantidad))

        # Mismo criterio que el core: una fila cuenta para la ubicación de reposición si el
        # parent_path de ésta está CONTENIDO en el de la fila (`in`, no `startswith`).
        ancestros = {}
        saldo = defaultdict(float)
        for producto_id, ubicacion, cantidad in filas:
            if not ubicacion:
                continue
            if ubicacion.id not in ancestros:
                ruta = ubicacion.parent_path
                ancestros[ubicacion.id] = [u.id for u in ubicaciones if u.parent_path in ruta]
            for destino_id in ancestros[ubicacion.id]:
                saldo[(producto_id, destino_id)] += cantidad

        redondeo = {p.id: p.uom_id.rounding for p in productos}
        con_negativo = {
            producto_id for (producto_id, _destino), valor in saldo.items()
            if float_compare(valor, 0, precision_rounding=redondeo[producto_id]) < 0}
        return productos.filtered(lambda p: p.id in con_negativo)

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
