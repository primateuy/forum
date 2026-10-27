{
    'name': 'FORUM - Descarga XLSX de reportes Cybrosys',
    'version': '17.0.1.0.0',
    'category': 'Extra Tools',
    'summary': 'El botón XLSX de los reportes de Cybrosys descarga el archivo en vez de caer en report_xlsx de OCA',
    'description': """
        Los reportes de Cybrosys (por ejemplo «PostgreSQL Query», psql_query_execute) piden un
        ir.actions.report con report_type 'xlsx' sin report_name, y mandan los datos a su ruta
        /xlsx_reports. report_xlsx de OCA atiende todo report_type 'xlsx', arma la URL con
        report_name y falla con «report.undefined modelo no fue encontrado».

        Este módulo registra un manejador que corre antes que el de OCA, toma sólo los pedidos
        con el formato de Cybrosys y los descarga desde /xlsx_reports. El resto sigue a OCA.
    """,
    'author': 'Primate',
    'website': 'https://primateuy.odoo.com',
    'depends': ['web', 'report_xlsx', 'psql_query_execute'],
    'assets': {
        'web.assets_backend': [
            'forum_xlsx_report_cybro/static/src/js/xlsx_report_handler.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
