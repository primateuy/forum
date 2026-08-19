from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Marca la exclusión de lógica de franquicia en los productos no almacenables.

    `excluir_logica_franquicia` pasó de ser un Boolean simple a un compute
    almacenado que viene en True para todo lo que no sea almacenable. Como la
    columna ya existía en la base, Odoo no recalcula los registros anteriores,
    así que se hace acá una única vez.

    Se incluyen los productos archivados (`active_test=False`): si se reactivan
    después, tienen que quedar con el valor correcto.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    templates = env['product.template'].with_context(active_test=False).search([
        ('type', '!=', 'product'),
    ])
    # El campo quedó en NULL en los productos anteriores a su creación, así que
    # se filtra en Python en lugar de buscar por `= False` en la base.
    pendientes = templates.filtered(lambda t: not t.excluir_logica_franquicia)
    pendientes.write({'excluir_logica_franquicia': True})
