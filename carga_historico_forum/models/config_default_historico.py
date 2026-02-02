from odoo import api, fields, models


class ConfigDefaultHistorico(models.Model):
    """
    Configuración de valores por defecto para carga histórica.

    Este modelo permite definir plantillas y valores fallback cuando
    existan datos faltantes durante la importación de facturas.
    """
    _name = 'config.default.historico'
    _description = 'Configuración Default Histórico'

    name = fields.Char(
        string='Nombre',
        required=True,
        default='Configuración Histórico',
    )
    active = fields.Boolean(
        string='Activo',
        default=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        help='Compañía a la que aplica esta configuración.',
    )
    default_partner_id = fields.Many2one(
        'res.partner',
        string='Partner por defecto',
        help='Partner plantilla para crear o usar cuando no existe el partner.',
    )
    default_product_id = fields.Many2one(
        'product.product',
        string='Producto por defecto',
        help='Producto plantilla para crear o usar cuando no existe el producto.',
    )
    default_journal_id = fields.Many2one(
        'account.journal',
        string='Diario por defecto',
        help='Diario a usar cuando el diario no existe en Odoo.',
    )
    default_company_id = fields.Many2one(
        'res.company',
        string='Compañía por defecto',
        help='Compañía a usar cuando la compañía no existe en Odoo.',
    )
    default_tax_ids = fields.Many2many(
        'account.tax',
        string='Impuestos por defecto',
        help='Impuestos a usar cuando el producto no tiene impuestos configurados.',
    )

    _sql_constraints = [
        (
            'config_default_historico_company_unique',
            'unique(company_id)',
            'Ya existe una configuración por compañía.',
        )
    ]

    @api.model
    def get_config_for_company(self, company_id):
        """
        Obtener configuración aplicable para una compañía.

        Primero se busca una configuración específica por compañía y luego
        una configuración global sin compañía definida.
        """
        # Bloque: búsqueda por compañía específica.
        if company_id:
            config = self.search(
                [('company_id', '=', company_id), ('active', '=', True)],
                limit=1,
            )
            if config:
                return config

        # Bloque: fallback a configuración global.
        return self.search(
            [('company_id', '=', False), ('active', '=', True)],
            limit=1,
        )
