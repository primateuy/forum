# -*- coding: utf-8 -*-
"""Reposición en segundo plano, por tandas encadenadas (estilo queue_job, sin cron).

Por qué existe. «Ordenar» con miles de reglas corría entero dentro de la petición del
usuario: con 6.550 reglas support la mató a los 120 s de CPU y no quedó nada (13-10-2026).
Forum puede llegar a reponer ~720.000 reglas de una vez.

Cómo funciona. El botón sólo crea el proceso y la lista de reglas (un INSERT … SELECT) y
responde enseguida. El trabajo lo hacen peticiones HTTP al propio Odoo, como los jobs de
queue_job: cada petición trabaja como mucho `PRESUPUESTO` segundos, en sub-lotes de
`SUBLOTE` reglas con un commit por sub-lote, y antes de terminar dispara la petición
siguiente y libera el worker. No hay cron ni hilo de fondo: si nada queda pendiente, nada
corre. Un lock de PostgreSQL asegura una sola tanda por vez en todo el servidor.

Si la cadena se corta (reinicio del servidor, worker matado), el proceso queda «estancado»
y se retoma con «Reanudar»; también se retoma solo cuando alguien crea otro proceso.
"""
import logging
import secrets
import threading
import time
from urllib.parse import urlparse

import requests

from odoo import _, api, fields, http, models
from odoo.exceptions import UserError
from odoo.tools import SQL, config, float_is_zero

_logger = logging.getLogger(__name__)

SUBLOTE = 300        # reglas por sub-lote: un commit cada uno
PRESUPUESTO = 60     # segundos de trabajo por petición (límites de support: 120 CPU / 240 reloj)
UMBRAL = 200         # hasta cuántas reglas «Ordenar» sigue siendo inmediato
ESTANCADO_MIN = 5    # sin avance en este tiempo, el proceso se muestra para reanudar
LOCK_KEY = 74201013  # advisory lock: una sola tanda por vez en todo el servidor
RUTA = '/forum_reorder_origin/reposicion/tanda'
PARAM_URL = 'forum_reorder_origin.reposicion_url'
PARAM_TOKEN = 'forum_reorder_origin.reposicion_token'
PARAM_UMBRAL = 'forum_reorder_origin.reposicion_umbral'
PARAM_SEGUNDOS = 'forum_reorder_origin.reposicion_segundos'
ESTADOS_ACTIVOS = ('cola', 'procesando')


def _en_test():
    return getattr(threading.current_thread(), 'testing', False)


_SESIONES = {}


def _sesion_con_base(dbname):
    """Sesión anónima con la base fijada, para la petición de la cadena.

    Odoo resuelve la base de una petición por la sesión o, si hay una sola visible para el
    Host, por el filtro de bases. Con varias bases en el servidor (los entornos locales) el
    Host no alcanza; la sesión sí. No tiene usuario: la autorización es el token.
    """
    store = http.root.session_store
    sid = _SESIONES.get(dbname)
    if sid and store.is_valid_key(sid) and store.get(sid).db == dbname:
        return sid
    sesion = store.new()
    sesion.update(http.get_default_session())
    sesion.db = dbname
    store.save(sesion)
    _SESIONES[dbname] = sesion.sid
    return sesion.sid


class ForumReposicionProceso(models.Model):
    _name = 'forum.reposicion.proceso'
    _description = 'Reposición en segundo plano'
    _order = 'id desc'

    name = fields.Char(string='Proceso', default='/', readonly=True, copy=False)
    user_id = fields.Many2one('res.users', string='Pedido por', default=lambda s: s.env.user,
                              ondelete='set null', readonly=True)
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company,
                                 ondelete='cascade', readonly=True)
    force_to_max = fields.Boolean(string='Al máximo', readonly=True)
    automatizar = fields.Boolean(string='Automatizar', readonly=True,
                                 help="Viene de «Automatizar»: las reglas pasan a disparo automático.")
    state = fields.Selection([
        ('cola', 'En cola'),
        ('procesando', 'Procesando'),
        ('hecho', 'Terminado'),
        ('cancelado', 'Cancelado'),
    ], string='Estado', default='cola', required=True, readonly=True, index=True)
    total = fields.Integer(readonly=True)
    procesadas = fields.Integer(readonly=True)
    repuestas = fields.Integer(readonly=True)
    sin_stock = fields.Integer(string='Sin stock en origen', readonly=True)
    errores = fields.Integer(string='Con error', readonly=True)
    omitidas = fields.Integer(readonly=True, help="Ya estaban en otro proceso, la regla no "
                                                  "existe más o no había nada que pedir.")
    omitidas_previas = fields.Integer(readonly=True, help="Las que ya estaban en otro proceso "
                                                          "al crearlo: no entran en el total.")
    progress = fields.Float(string='Avance', compute='_compute_progress')
    estancado = fields.Boolean(compute='_compute_estancado')
    started_at = fields.Datetime(string='Inicio', readonly=True)
    ended_at = fields.Datetime(string='Fin', readonly=True)
    heartbeat = fields.Datetime(string='Último avance', readonly=True)
    paso = fields.Char(string='Paso', readonly=True)
    log = fields.Text(readonly=True)
    linea_ids = fields.One2many('forum.reposicion.proceso.regla', 'proceso_id', readonly=True)
    picking_ids = fields.Many2many('stock.picking', string='Operaciones', readonly=True, copy=False,
                                   help="Operaciones a las que el proceso les sumó movimientos. "
                                        "Las reglas se reponen como con «Ordenar»: en la operación "
                                        "abierta de cada sucursal.")
    picking_count = fields.Integer(string='Operaciones', compute='_compute_picking_count')

    @api.model_create_multi
    def create(self, vals_list):
        Seq = self.env['ir.sequence'].sudo()
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = Seq.next_by_code('forum.reposicion.proceso') or '/'
        return super().create(vals_list)

    @api.depends('total', 'procesadas')
    def _compute_progress(self):
        for proceso in self:
            proceso.progress = 100.0 * proceso.procesadas / proceso.total if proceso.total else 0.0

    @api.depends('state', 'heartbeat')
    def _compute_estancado(self):
        limite = fields.Datetime.subtract(fields.Datetime.now(), minutes=ESTANCADO_MIN)
        for proceso in self:
            ultimo = proceso.heartbeat or proceso.create_date
            proceso.estancado = bool(proceso.state in ESTADOS_ACTIVOS and ultimo and ultimo < limite)

    @api.depends('picking_ids')
    def _compute_picking_count(self):
        for proceso in self:
            proceso.picking_count = len(proceso.picking_ids)

    # ------------------------------------------------------------------
    # Alta del proceso (lo único que corre en la petición del usuario)
    # ------------------------------------------------------------------
    @api.model
    def _umbral(self):
        try:
            return int(self.env['ir.config_parameter'].sudo().get_param(PARAM_UMBRAL, UMBRAL))
        except (TypeError, ValueError):
            return UMBRAL

    @api.model
    def _presupuesto(self):
        """Segundos de trabajo por petición. Por parámetro, para afinarlo sin tocar código;
        siempre lejos del límite de CPU del worker."""
        try:
            valor = int(self.env['ir.config_parameter'].sudo().get_param(PARAM_SEGUNDOS, PRESUPUESTO))
        except (TypeError, ValueError):
            valor = PRESUPUESTO
        return max(1, min(valor, 90))

    @api.model
    def _controlar_permiso(self, cantidad):
        """Reponer en segundo plano es del grupo «Reposición masiva». Sin él, se ordena como
        siempre hasta el umbral; por encima, se avisa en vez de correrlo en la petición, que
        es justo lo que el servidor corta."""
        if not self.env.user.has_group('forum_reorder_origin.group_reposicion_masiva'):
            raise UserError(_(
                "Seleccionaste %(n)s reglas. Para ordenar más de %(umbral)s reglas de una vez hace "
                "falta el permiso «Reposición masiva» (Ajustes › Usuarios). Sin él, ordená de a "
                "%(umbral)s como máximo.", n=cantidad, umbral=self._umbral()))

    @api.model
    def _crear(self, orderpoints=None, dominio=None, force_to_max=False, automatizar=False):
        """Crea el proceso con las reglas (ids o dominio) y dispara la primera tanda.

        Las reglas se insertan con un solo INSERT … SELECT ordenado por producto: así las de
        un mismo producto caen en el mismo sub-lote y el control de stock en origen las
        evalúa juntas. Las que ya esperan en otro proceso activo se omiten, para no reponer
        dos veces.
        """
        Orderpoint = self.env['stock.warehouse.orderpoint']
        if dominio is not None:
            seleccion = Orderpoint._search(dominio).subselect()
        else:
            seleccion = SQL('(SELECT unnest(%s::int[]))', list(orderpoints.ids))
        proceso = self.create({'force_to_max': force_to_max, 'automatizar': automatizar})
        self.env.flush_all()
        self.env.cr.execute(SQL("""
            WITH elegidas AS (
                SELECT op.id, op.product_id, op.location_id
                  FROM stock_warehouse_orderpoint op
                 WHERE op.id IN %(seleccion)s
            ), libres AS (
                SELECT e.* FROM elegidas e
                 WHERE NOT EXISTS (
                       SELECT 1 FROM forum_reposicion_proceso_regla r
                         JOIN forum_reposicion_proceso p ON p.id = r.proceso_id
                        WHERE r.orderpoint_id = e.id AND r.estado = 'pendiente'
                          AND p.state IN ('cola', 'procesando'))
            ), alta AS (
                INSERT INTO forum_reposicion_proceso_regla
                       (proceso_id, orderpoint_id, product_id, location_id, estado, secuencia,
                        create_uid, create_date, write_uid, write_date)
                SELECT %(proceso)s, l.id, l.product_id, l.location_id, 'pendiente',
                       row_number() OVER (ORDER BY l.product_id, l.location_id, l.id),
                       %(uid)s, now() AT TIME ZONE 'UTC', %(uid)s, now() AT TIME ZONE 'UTC'
                  FROM libres l
                RETURNING 1
            )
            SELECT (SELECT count(*) FROM elegidas), (SELECT count(*) FROM alta)
        """, seleccion=seleccion, proceso=proceso.id, uid=self.env.uid))
        elegidas, alta = self.env.cr.fetchone()
        self.env['forum.reposicion.proceso.regla'].invalidate_model()
        proceso.invalidate_recordset(['linea_ids'])
        proceso.write({'total': alta, 'omitidas': elegidas - alta,
                       'omitidas_previas': elegidas - alta})
        if elegidas - alta:
            proceso._registrar(_("%s regla(s) ya estaban en otro proceso en curso: se omiten.")
                               % (elegidas - alta))
        if not alta:
            proceso.write({'state': 'hecho', 'ended_at': fields.Datetime.now(),
                           'paso': _("Nada para reponer")})
        else:
            self._encadenar()
        return proceso

    def _notificacion_creado(self):
        self.ensure_one()
        url = '/web#id=%s&model=%s&view_type=form' % (self.id, self._name)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reposición en segundo plano: %s') % self.name,
                'message': _('%(n)s regla(s) se están reponiendo por tandas. Podés seguir '
                             'trabajando; el avance está en %%s.', n=self.total),
                'links': [{'label': _('Inventario › Procesos de reposición'), 'url': url}],
                'type': 'info',
                'sticky': False,
            },
        }

    # ------------------------------------------------------------------
    # Cadena de tandas (estilo queue_job)
    # ------------------------------------------------------------------
    @api.model
    def _token(self):
        Param = self.env['ir.config_parameter'].sudo()
        token = Param.get_param(PARAM_TOKEN)
        if not token:
            token = secrets.token_urlsafe(32)
            Param.set_param(PARAM_TOKEN, token)
        return token

    @api.model
    def _url_tanda(self):
        """La petición va al propio servidor por la interfaz local, con el Host público para
        que el filtro de bases resuelva la base. Se puede fijar entera por parámetro."""
        Param = self.env['ir.config_parameter'].sudo()
        url = Param.get_param(PARAM_URL)
        if url:
            return url, None
        puerto = config.get('http_port') or 8069
        interfaz = config.get('http_interface') or '127.0.0.1'
        if interfaz in ('0.0.0.0', '::'):
            interfaz = '127.0.0.1'
        host = urlparse(Param.get_param('web.base.url') or '').netloc or None
        return 'http://%s:%s%s' % (interfaz, puerto, RUTA), host

    @api.model
    def _encadenar(self):
        """Pide, SIN esperar, que el propio Odoo corra la próxima tanda.

        Sale después del commit (si saliera antes, la tanda nueva no vería lo recién
        grabado). El POST se corta al segundo: no se espera la respuesta, la tanda sigue en
        el worker que la atiende y este worker queda libre.

        Es sincrónico a propósito, no un hilo aparte: en multi-worker Odoo recicla el worker
        que pasó el límite de memoria apenas responde, y un hilo daemon muere con él antes
        de mandar nada. Pasó en la prueba local del 13-10-2026: la cadena se cortó después
        de la primera tanda.
        """
        if _en_test():
            return
        url, host = self._url_tanda()
        datos = {'jsonrpc': '2.0', 'method': 'call', 'params': {'token': self._token()}}
        cabeceras = {'Content-Type': 'application/json'}
        if host:
            cabeceras['Host'] = host
        dbname = self.env.cr.dbname

        def disparar():
            # Sin proxies del entorno: la llamada es al propio servidor. Además, en macOS
            # leer el proxy del sistema dentro de un worker (proceso hijo de un fork) mata
            # el proceso en seco; pasó en la prueba local y cortaba la cadena.
            sesion = requests.Session()
            sesion.trust_env = False
            try:
                sesion.post(url, json=datos, headers=cabeceras, timeout=(5, 1),
                            cookies={'session_id': _sesion_con_base(dbname)})
            except requests.exceptions.ReadTimeout:
                pass  # esperado: la tanda sigue corriendo en el otro worker
            except Exception as e:
                _logger.warning("[reposición] no se pudo disparar la tanda siguiente: %s", e)
            finally:
                sesion.close()

        self.env.cr.postcommit.add(disparar)

    @api.model
    def _correr_tanda(self, token):
        """Una petición de la cadena: trabaja hasta PRESUPUESTO segundos y encadena la otra."""
        if not token or not secrets.compare_digest(token, self._token()):
            return {'estado': 'token inválido'}
        cr = self.env.cr
        cr.execute('SELECT pg_try_advisory_lock(%s)', [LOCK_KEY])
        if not cr.fetchone()[0]:
            return {'estado': 'ocupado'}  # ya hay una tanda corriendo; esa encadena la siguiente
        quedan = False
        try:
            inicio, presupuesto = time.time(), self._presupuesto()
            while time.time() - inicio < presupuesto:
                proceso = self.search([('state', 'in', ESTADOS_ACTIVOS)], order='id', limit=1)
                if not proceso:
                    break
                proceso._procesar_sublote()
            quedan = bool(self.search_count([('state', 'in', ESTADOS_ACTIVOS)]))
        finally:
            cr.execute('SELECT pg_advisory_unlock(%s)', [LOCK_KEY])
        if quedan:
            self._encadenar()
        self._commit()  # el commit dispara el postcommit con la tanda siguiente
        return {'estado': 'sigue' if quedan else 'listo'}

    # ------------------------------------------------------------------
    # Un sub-lote
    # ------------------------------------------------------------------
    def _procesar_sublote(self):
        """Repone el próximo sub-lote de reglas pendientes de este proceso y commitea."""
        self.ensure_one()
        cr = self.env.cr
        Linea = self.env['forum.reposicion.proceso.regla']
        lineas = Linea.search([('proceso_id', '=', self.id), ('estado', '=', 'pendiente')],
                              order='secuencia', limit=SUBLOTE)
        if not lineas:
            self._terminar()
            self._commit()
            return False
        if self.state == 'cola':
            self.write({'state': 'procesando', 'started_at': fields.Datetime.now()})
        n_sublote = (lineas[0].secuencia - 1) // SUBLOTE + 1
        self.write({'paso': _("Sub-lote %s: reglas %s a %s de %s") % (
            n_sublote, lineas[0].secuencia, lineas[-1].secuencia, self.total)})
        try:
            with cr.savepoint():
                resultado = self._reponer(lineas)
        except Exception as e:  # una falla inesperada no traba el proceso: se anota y sigue
            _logger.exception("[reposición] %s: falló el sub-lote %s", self.name, n_sublote)
            del self.env.cr.cache.setdefault('forum_reposicion_errores', [])[:]
            resultado = {linea.id: ('error', str(e)[:500]) for linea in lineas}
        for estado in ('repuesta', 'sin_stock', 'error', 'omitida'):
            ids = [lid for lid, (est, _m) in resultado.items() if est == estado]
            if not ids:
                continue
            for lid in ids:
                motivo = resultado[lid][1]
                if motivo:
                    Linea.browse(lid).motivo = motivo
            Linea.browse(ids).write({'estado': estado})
        self._actualizar_contadores()
        self._commit()
        return True

    def _reponer(self, lineas):
        """Devuelve {linea_id: (estado, motivo)}."""
        Orderpoint = self.env['stock.warehouse.orderpoint'].with_company(self.company_id)
        if self.user_id:
            Orderpoint = Orderpoint.with_user(self.user_id)
        resultado = {}
        por_regla = {}
        for linea in lineas:
            if not linea.orderpoint_id or not linea.orderpoint_id.active:
                resultado[linea.id] = ('omitida', _("La regla ya no existe o está archivada."))
            else:
                por_regla[linea.orderpoint_id.id] = linea.id
        reglas = Orderpoint.browse(list(por_regla))
        if not reglas:
            return resultado

        # La cantidad a pedir se recalcula ahora: el recálculo es diferido
        # (reorden_rendimiento) y una tanda anterior pudo haberla cambiado.
        # El pronóstico no se almacena: en la misma petición corren varios sub-lotes y uno
        # anterior pudo cambiarlo, así que se descarta lo que haya en caché.
        reglas.invalidate_recordset(['qty_on_hand', 'qty_forecast'])
        campos = self.env['reorden.recalculo.pendiente']._campos()
        for campo in campos:
            self.env.add_to_compute(campo, reglas)
        reglas.flush_recordset([c.name for c in campos])

        if self.force_to_max:
            # Lo mismo que hace el core con force_to_max, pero ANTES del control de stock en
            # origen: así se controla lo que de verdad se va a pedir.
            for op in reglas:
                op.qty_to_order = op.product_max_qty - op.qty_forecast
                resto = op.qty_multiple > 0 and op.qty_to_order % op.qty_multiple or 0.0
                if not float_is_zero(resto, precision_rounding=op.product_uom.rounding):
                    op.qty_to_order += op.qty_multiple - resto
        nada = reglas.filtered(lambda o: o.qty_to_order <= 0)
        for op in nada:
            resultado[por_regla[op.id]] = ('omitida', _("No había nada para pedir."))
        reglas -= nada

        # Sin stock en origen: se saltean y se listan (decisión de Daryl, 13-10-2026).
        faltan = {item['orderpoint_id']: item for item in reglas._check_origin_stock()}
        for op_id, item in faltan.items():
            resultado[por_regla[op_id]] = ('sin_stock', _(
                "Disponible en %(origen)s: %(disp)s; esta regla pide %(pide)s y las %(n)s reglas "
                "del mismo origen piden %(total)s.", origen=item['origin_warehouse'],
                disp=item['available'], pide=item['requested'], n=item['group_count'],
                total=item['group_requested']))
        reglas = reglas.filtered(lambda o: o.id not in faltan)
        if not reglas:
            return resultado

        if self.automatizar:
            reglas.write({'trigger': 'auto'})
        self.env.flush_all()
        self.env.cr.execute('SELECT coalesce(max(id), 0) FROM stock_move')
        ultimo_move = self.env.cr.fetchone()[0]
        errores = self.env.cr.cache.setdefault('forum_reposicion_errores', [])
        del errores[:]
        # Sin grupo propio, a propósito: igual que «Ordenar», las líneas se suman a la
        # operación abierta de cada sucursal. Con un grupo por sub-lote, 6.550 reglas daban
        # 2.505 operaciones chicas (≈ 22 preparaciones por sucursal); decisión de Daryl,
        # 13-10-2026.
        reglas.with_context(forum_reposicion_fondo=True, reposicion_tolerante=True,
                            stock_proceso_masivo=True, wis_encolar_envios=True,
                            ).action_replenish()
        self._registrar_operaciones(ultimo_move)
        con_error = {}
        for orderpoint, mensaje in errores:
            if orderpoint and orderpoint.id in por_regla:
                con_error[orderpoint.id] = (mensaje or '').strip().splitlines()[0][:500]
        del errores[:]
        for op_id in reglas.ids:
            resultado[por_regla[op_id]] = (('error', con_error[op_id]) if op_id in con_error
                                           else ('repuesta', False))
        return resultado

    def _registrar_operaciones(self, ultimo_move):
        """Anota las operaciones que recibieron movimientos en este sub-lote.

        Son los movimientos creados en ESTA transacción (cada sub-lote tiene la suya, y
        Odoo graba create_date con la hora de la transacción). No se usa la regla del
        movimiento: el core borra las reglas manuales que quedan en cero y el vínculo se
        pierde.
        """
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT DISTINCT picking_id FROM stock_move
             WHERE id > %s AND picking_id IS NOT NULL
               AND create_date = (now() AT TIME ZONE 'UTC')""", [ultimo_move])
        ids = [r[0] for r in self.env.cr.fetchall()]
        if ids:
            self.sudo().write({'picking_ids': [(4, i) for i in ids]})

    def _actualizar_contadores(self):
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT estado, count(*) FROM forum_reposicion_proceso_regla
             WHERE proceso_id = %s GROUP BY estado""", [self.id])
        cuenta = dict(self.env.cr.fetchall())
        self.write({
            'procesadas': sum(v for k, v in cuenta.items() if k != 'pendiente'),
            'repuestas': cuenta.get('repuesta', 0),
            'sin_stock': cuenta.get('sin_stock', 0),
            'errores': cuenta.get('error', 0),
            'omitidas': cuenta.get('omitida', 0) + self.omitidas_previas,
            'heartbeat': fields.Datetime.now(),
        })

    def _terminar(self):
        self.ensure_one()
        if self.state not in ESTADOS_ACTIVOS:
            return
        self._actualizar_contadores()
        self.write({'state': 'hecho', 'ended_at': fields.Datetime.now(), 'paso': False})
        resumen = _("Terminado: %(rep)s repuestas, %(sin)s sin stock en origen, %(err)s con error, "
                    "%(omi)s omitidas, de %(tot)s.", rep=self.repuestas, sin=self.sin_stock,
                    err=self.errores, omi=self.omitidas, tot=self.total)
        self._registrar(resumen)
        if self.user_id:
            self.env['bus.bus']._sendone(self.user_id.partner_id, 'simple_notification', {
                'title': _('Reposición %s terminada') % self.name,
                'message': resumen,
                'sticky': bool(self.sin_stock or self.errores),
                'type': 'warning' if (self.sin_stock or self.errores) else 'success',
            })

    def _registrar(self, texto):
        for proceso in self:
            linea = '[%s] %s' % (fields.Datetime.now(), texto)
            proceso.log = (proceso.log + '\n' + linea) if proceso.log else linea

    def _commit(self):
        if not _en_test():
            self.env.cr.commit()

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------
    def action_cancelar(self):
        activos = self.filtered(lambda p: p.state in ESTADOS_ACTIVOS)
        activos.write({'state': 'cancelado', 'ended_at': fields.Datetime.now(), 'paso': False})
        activos._registrar(_("Cancelado por %s. Lo ya repuesto queda; lo pendiente no se repone.")
                           % self.env.user.name)
        return True

    def action_reanudar(self):
        for proceso in self:
            if proceso.state == 'cancelado':
                proceso.write({'state': 'procesando' if proceso.started_at else 'cola',
                               'ended_at': False})
                proceso._registrar(_("Reanudado por %s.") % self.env.user.name)
            elif proceso.state not in ESTADOS_ACTIVOS:
                raise UserError(_("El proceso %s ya terminó.") % proceso.name)
        self._encadenar()
        return True

    def action_ver_reglas_con_problema(self):
        self.ensure_one()
        ids = self.linea_ids.filtered(
            lambda l: l.estado in ('sin_stock', 'error')).orderpoint_id.ids
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reglas sin reponer de %s') % self.name,
            'res_model': 'stock.warehouse.orderpoint',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', ids)],
        }

    def action_ver_operaciones(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Operaciones de %s') % self.name,
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.picking_ids.ids)],
        }


class ForumReposicionProcesoRegla(models.Model):
    _name = 'forum.reposicion.proceso.regla'
    _description = 'Regla de un proceso de reposición'
    _order = 'secuencia'

    proceso_id = fields.Many2one('forum.reposicion.proceso', required=True, ondelete='cascade',
                                 index=True)
    orderpoint_id = fields.Many2one('stock.warehouse.orderpoint', string='Regla',
                                    ondelete='set null', index=True)
    product_id = fields.Many2one('product.product', string='Producto', ondelete='set null')
    location_id = fields.Many2one('stock.location', string='Ubicación', ondelete='set null')
    estado = fields.Selection([
        ('pendiente', 'Pendiente'),
        ('repuesta', 'Repuesta'),
        ('sin_stock', 'Sin stock en origen'),
        ('error', 'Error'),
        ('omitida', 'Omitida'),
    ], required=True, default='pendiente', index=True)
    motivo = fields.Char()
    secuencia = fields.Integer(index=True)

    def init(self):
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS forum_reposicion_regla_pendiente_idx
                ON forum_reposicion_proceso_regla (proceso_id, estado, secuencia)""")
