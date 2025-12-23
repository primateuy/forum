# -*- coding: utf-8 -*-

from odoo import models, fields, api


class AccountMove(models.Model):
    """
    Extensión del modelo account.move para agregar campos de migración.
    
    Este modelo agrega campos adicionales al encabezado de factura que permiten
    rastrear información del sistema origen durante procesos de migración de datos.
    """
    _inherit = "account.move"

    # Campo de selección para identificar el origen de migración
    # Identifica el sistema origen (POS legado, ERP legado, etc.)
    x_mig_source = fields.Selection(
        selection=[
            ('pos_legacy', 'POS Legado'),
            ('erp_legacy', 'ERP Legado'),
            ('manual', 'Manual'),
            ('other', 'Otro'),
        ],
        string='Origen de migración',
        help='Identifica el sistema origen de donde proviene esta factura durante la migración.',
        tracking=True,
    )

    # ID del documento en el sistema origen
    # Permite trazabilidad y deduplicación con el sistema origen
    x_mig_source_document_id = fields.Char(
        string='ID documento origen',
        help='ID del documento en el sistema origen. Permite trazabilidad y deduplicación.',
        tracking=True,
    )

    # Código del cliente en el sistema origen
    # Útil para mapeo/búsqueda aunque el partner sea genérico en Odoo
    x_mig_partner_code = fields.Char(
        string='Código cliente (origen)',
        help='Código del cliente en el sistema origen. Útil para mapeo y búsqueda.',
        tracking=True,
    )

