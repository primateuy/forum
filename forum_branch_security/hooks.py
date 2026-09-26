# -*- coding: utf-8 -*-
"""Siembra y migración del perfil de sucursal.

Todo vive en el post_init_hook y no en migrations/ porque **un script de migración no
corre en la primera instalación**: Odoo solo ejecuta migrations/<version>/ cuando la
versión instalada cambia. Para un módulo nuevo el único punto de entrada es el hook.

`migrations/17.0.1.0.0/post-migrate.py` llama a la misma función, para el caso de que el
módulo se actualice sobre un estado anterior.

Todo es idempotente: correrlo dos veces no rompe nada ni duplica nada.
"""
import logging

_logger = logging.getLogger(__name__)

# Reportes que exponen costo, margen o configuración de abastecimiento. Los de operación
# —remito, hoja de conteo, etiquetas, recepción, devolución— se dejan: son los que el
# perfil necesita para los cuatro flujos.
HIDDEN_REPORTS = [
    'mrp_account_enterprise.action_cost_struct_product_template',
    'product.action_report_pricelist',
    'stock.action_report_stock_rule',
]

# Reglas de CORE que alguien archivó para que un usuario de franquicia viera listas de
# precios de la casa central. Con la jerarquía de compañías declarada, el `parent_of` de
# su propio dominio ya lo resuelve y archivarlas era innecesario.
#
# Solo estas dos. Las reglas creadas a mano NO se tocan: se reportan en el log.
CORE_RULES_TO_UNARCHIVE = [
    'product.product_pricelist_comp_rule',
    'product.product_pricelist_item_comp_rule',
]


def post_init_hook(env):
    _hide_reports(env)
    _migrate_branches_from_pos_restrict(env)
    _unarchive_core_rules(env)
    _report_handmade_rules(env)
    _grant_cost_group(env)
    _archive_empty_company_pricelists(env)


# ---------------------------------------------------------------- reportes
def _hide_reports(env):
    group = env.ref('forum_branch_security.group_branch_user')
    for xmlid in HIDDEN_REPORTS:
        report = env.ref(xmlid, raise_if_not_found=False)
        if not report:
            _logger.info('Perfil sucursal: el reporte %s no está instalado, se saltea.', xmlid)
            continue
        report.hide_for_group_ids = [(4, group.id)]
    _logger.info('Perfil sucursal: reportes bloqueados revisados.')


# ---------------------------------------------------------------- migración
def _is_dummy_warehouse(env, warehouse):
    """Los almacenes tecnicos `z_<Compania>` no son locales.

    FORUM es dueno de la mercaderia hasta que se vende: hay un almacen por local, todos
    de la casa central, incluidos los de los locales de franquicia. Cada compania de
    franquicia tiene ademas UN solo almacen tecnico que le sirve a todos sus locales.

    Firma del dummy, sin parsear nombres: es el unico almacen de una compania que no es
    la raiz de la jerarquia. Asignarlo como sucursal juntaria en un mismo "local" a
    varias sucursales distintas, y el usuario de una veria los datos de la otra.
    """
    company = warehouse.company_id
    if not company.parent_id:
        return False
    hermanos = env['stock.warehouse'].search_count([('company_id', '=', company.id)])
    return hermanos == 1


def _derive_branch_warehouse(env, user):
    """Devuelve el almacen que representa la sucursal del usuario, o None.

    Fuente primaria: `pad_local_id`, el mapeo explicito local->almacen que ya mantiene
    advanced_dashboard_forum_data. Resuelve bien el caso franquicia, donde el PDV es del
    franquiciado y el almacen de la casa central.

    Fallback, si ese modulo no esta instalado: `pos_config.picking_type_id.warehouse_id`.
    Eso **falla en las franquicias**, porque picking_type_id no cruza companias y
    devuelve el almacen tecnico de la compania en vez del local. Cuando detecta ese caso
    devuelve None para que el usuario quede listado para asignacion manual, en vez de
    asignarle en silencio el almacen equivocado.
    """
    configs = user.allowed_pos
    if not configs:
        return None

    if 'pad_local_id' in env['res.users']._fields and user.pad_local_id:
        return user.pad_local_id

    if 'pad_local_id' in env['pos.config']._fields:
        locales = configs.pad_local_id
        if len(locales) == 1:
            return locales
        return None

    warehouses = configs.picking_type_id.warehouse_id
    if len(warehouses) != 1:
        return None
    if _is_dummy_warehouse(env, warehouses):
        return None
    return warehouses


def _migrate_branches_from_pos_restrict(env):
    """Puebla el ancla de sucursal desde el vinculo que existe hoy.

    `stock.warehouse.user_ids` de user_warehouse_restriction esta vacio —ese modulo nunca
    llego a instalarse—, asi que la fuente real es `res.users.allowed_pos`, de
    pos_restrict.

    Pero `allowed_pos` da usuario->PDV y el ancla es el almacen, asi que hay que derivarlo.
    Ver _derive_branch_warehouse: los que no se pueden derivar con certeza se LISTAN en el
    log para asignacion manual. Sin ese reporte la migracion dejaria un subconjunto
    silencioso de usuarios con la sucursal equivocada.
    """
    if 'allowed_pos' not in env['res.users']._fields:
        _logger.warning(
            'Perfil sucursal: pos_restrict no esta instalado, no hay de donde migrar.')
        return

    users = env['res.users'].search([('allowed_pos', '!=', False)])
    sin_almacen = []
    migrados = 0

    for user in users:
        warehouse = _derive_branch_warehouse(env, user)
        if not warehouse:
            sin_almacen.append(user)
            continue

        configs = user.allowed_pos
        if 'pad_local_id' in env['pos.config']._fields:
            propios = configs.filtered(lambda c: c.pad_local_id == warehouse)
            configs = propios or configs

        vals = {}
        if not warehouse.is_branch:
            vals['is_branch'] = True
        faltan = configs - warehouse.branch_pos_config_ids
        if faltan:
            vals['branch_pos_config_ids'] = [(4, c.id) for c in faltan]
        if user not in warehouse.branch_user_ids:
            vals['branch_user_ids'] = [(4, user.id)]

        # Idempotencia correctiva: si una corrida anterior le asigno OTRA sucursal,
        # se la saca. Si no, el usuario acumularia locales que no le corresponden.
        sobrantes = user.branch_warehouse_ids - warehouse
        if sobrantes:
            _logger.info(
                'Perfil sucursal: %s tenia asignadas ademas %s; se corrige a %s.',
                user.login,
                ', '.join(sobrantes.mapped('display_name')),
                warehouse.display_name)
            user.branch_warehouse_ids = [(3, w.id) for w in sobrantes]

        if vals:
            warehouse.write(vals)
        migrados += 1

    _logger.info('Perfil sucursal: %s usuarios migrados desde allowed_pos.', migrados)

    if sin_almacen:
        _logger.warning(
            'Perfil sucursal: %s usuarios con PDV pero SIN almacen derivable con '
            'certeza. Hay que asignarles la sucursal a mano en la ficha del usuario:',
            len(sin_almacen))
        for user in sin_almacen:
            _logger.warning(
                '    %-45s (compania %-20s) PDV: %s',
                user.login,
                user.company_id.name,
                ', '.join(user.allowed_pos.mapped('name')) or '(ninguno)')

    env['res.users'].search(
        [('branch_warehouse_ids', '!=', False)])._sync_branch_companies()


# ---------------------------------------------------------------- reglas
def _unarchive_core_rules(env):
    for xmlid in CORE_RULES_TO_UNARCHIVE:
        rule = env.ref(xmlid, raise_if_not_found=False)
        if not rule:
            _logger.warning('Perfil sucursal: no existe la regla %s.', xmlid)
            continue
        if rule.active:
            continue
        rule.active = True
        _logger.info(
            'Perfil sucursal: se desarchiva la regla de core %s (%s sobre %s). '
            'Su dominio usa parent_of y la jerarquía de compañías ya está declarada, '
            'así que archivarla era innecesario.',
            xmlid, rule.name, rule.model_id.model)


def _report_handmade_rules(env):
    """Reporta, sin tocar, las reglas creadas a mano.

    No se desarchivan ni se borran: hay que revisarlas a ojo antes. Dos de ellas matchean
    el APELLIDO del usuario contra el nombre del almacén, que es la razón por la que
    estaban archivadas — así no dejaban pasar nada.
    """
    rules = env['ir.rule'].with_context(active_test=False).search([])
    handmade = rules.filtered(
        lambda r: not env['ir.model.data'].search_count([
            ('model', '=', 'ir.rule'), ('res_id', '=', r.id),
        ]))
    if not handmade:
        return
    _logger.warning(
        'Perfil sucursal: hay %s reglas ir.rule creadas a mano (sin ir_model_data). '
        'NO se tocaron. Revisalas antes de eliminarlas:', len(handmade))
    for rule in handmade:
        _logger.warning(
            '    id=%-5s activa=%-5s %-28s %s',
            rule.id, rule.active, rule.model_id.model, rule.name)


# ---------------------------------------------------------------- costo
def _grant_cost_group(env):
    """Otorga el grupo de costo con radio cero.

    `standard_price` pasa de groups="base.group_user" a este grupo. Para que el día del
    deploy no cambie nada para nadie, se le otorga a **todos los usuarios internos
    actuales menos los del perfil sucursal**. El mecanismo queda montado y después se
    saca gente deliberadamente.

    Ojo: un usuario interno creado DESPUÉS de esto no lo recibe solo. Hay que dárselo a
    mano o el costo le queda oculto.
    """
    cost_group = env.ref('forum_branch_security.group_product_cost')
    branch_group = env.ref('forum_branch_security.group_branch_user')
    internal = env.ref('base.group_user')

    candidatos = env['res.users'].with_context(active_test=False).search([
        ('groups_id', 'in', internal.id),
        ('share', '=', False),
    ])
    destinatarios = candidatos.filtered(lambda u: branch_group not in u.groups_id)
    nuevos = destinatarios.filtered(lambda u: cost_group not in u.groups_id)

    if nuevos:
        cost_group.sudo().write({'users': [(4, u.id) for u in nuevos]})

    _logger.info(
        'Perfil sucursal: grupo "Ver costo de productos" otorgado a %s usuarios '
        '(%s ya lo tenían, %s excluidos por ser del perfil sucursal).',
        len(nuevos), len(destinatarios) - len(nuevos),
        len(candidatos) - len(destinatarios))


# ---------------------------------------------------------------- listas
def _archive_empty_company_pricelists(env):
    """Archiva las listas de precios vacías que Odoo crea por compañía.

    Son ruido: una por compañía, sin ítems, sin PDV y sin pedidos. La convención de FORUM
    es que las listas viven en la casa central o sin compañía, nunca dentro de la
    compañía de una franquicia.

    Solo archiva las que están **completamente vacías**. Cualquier lista con un ítem, un
    PDV o un pedido queda intacta.
    """
    pricelists = env['product.pricelist'].search([('company_id', '!=', False)])
    a_archivar = env['product.pricelist']
    for pricelist in pricelists:
        if pricelist.item_ids:
            continue
        if env['pos.config'].search_count(['|',
                                           ('pricelist_id', '=', pricelist.id),
                                           ('available_pricelist_ids', 'in', pricelist.id)]):
            continue
        if env['sale.order'].search_count([('pricelist_id', '=', pricelist.id)]):
            continue
        a_archivar |= pricelist

    if not a_archivar:
        _logger.info('Perfil sucursal: no hay listas de precios vacías para archivar.')
        return

    a_archivar.write({'active': False})
    _logger.info(
        'Perfil sucursal: se archivaron %s listas de precios vacías de compañía: %s',
        len(a_archivar),
        ', '.join('%s (%s)' % (p.name, p.company_id.name) for p in a_archivar))
