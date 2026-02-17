# -*- coding: utf-8 -*-

from collections import defaultdict
import logging
import re

import psycopg2
from psycopg2 import extras

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


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

    @api.model
    def _safe_int(self, value):
        """
        Convertir un valor a entero de forma segura.

        Este método evita errores al convertir textos a enteros y centraliza
        la lógica de normalización de IDs provenientes del histórico.
        """
        # Bloque: descartar booleanos para evitar True/False como 1/0.
        if isinstance(value, bool):
            return False

        # Bloque: retorno directo si el valor ya es entero válido.
        if isinstance(value, int):
            return value

        # Bloque: conversión defensiva para textos numéricos directos.
        try:
            return int(value)
        except (TypeError, ValueError):
            # Bloque: extracción de dígitos desde cualquier tipo convertible a texto.
            text_value = str(value or '').strip()
            if not text_value:
                return False
            match = re.search(r"(\d+)", text_value)
            if match:
                return int(match.group(1))
            return False

    @api.model
    def _get_historic_db_connection(self):
        """
        Obtener conexión a la base de datos histórica.

        La conexión se construye con parámetros configurados en ir.config_parameter
        para mantener la configuración fuera del código y permitir cambios sin deploy.
        """
        # Bloque: lectura de parámetros desde configuración del sistema.
        config = self.env['ir.config_parameter'].sudo()
        db_name = config.get_param('forum_historico.db_name')
        db_user = config.get_param('forum_historico.db_user')
        db_password = config.get_param('forum_historico.db_password')
        db_host = config.get_param('forum_historico.db_host') or 'localhost'
        db_port = config.get_param('forum_historico.db_port') or '5432'

        # Bloque: validación básica para evitar conexiones incompletas.
        if not db_name or not db_user:
            _logger.error(
                "Falta configurar parámetros de conexión al histórico "
                "(forum_historico.db_name y forum_historico.db_user)."
            )
            return False

        # Bloque: construcción y retorno de la conexión psycopg2.
        return psycopg2.connect(
            dbname=db_name,
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port,
        )

    @api.model
    def _fetch_pending_historic_invoices(self, cursor, line_limit):
        """
        Obtener facturas pendientes desde el histórico en base a límite de líneas.

        Se utiliza el límite como cantidad de facturas a procesar por ejecución
        del cron, evitando cargas masivas de una sola corrida.
        """
        # Bloque: retorno temprano si el límite no es válido.
        if not line_limit or line_limit <= 0:
            return []

        # Bloque: consulta simple para limitar por cantidad de facturas.
        query = """
            SELECT
                invoice_id,
                invoice_local_date,
                odoo_partner_id,
                odoo_journal_id,
                odoo_company_id,
                q_lineas,
                invoice_ticket_count
            FROM forum_his_invoice
            WHERE procesado = FALSE
            ORDER BY invoice_id
            LIMIT %s
        """
        cursor.execute(query, (line_limit,))
        return cursor.fetchall()

    @api.model
    def _fetch_historic_invoice_lines(self, cursor, invoice_ids):
        """
        Obtener líneas de facturas históricas para un conjunto de invoice_id.

        Se retorna una lista de registros para agrupar en memoria por factura.
        """
        # Bloque: retorno temprano si no hay facturas.
        if not invoice_ids:
            return []

        # Bloque: consulta parametrizada con filtro por lista de IDs.
        # Columnas de migración: deben existir en forum_his_invoice_detail para copiarse.
        # NO se cargan: product_tags_snapshot, price_group_snapshot_id, price_group_snapshot.
        query = """
            SELECT
                invoice_detail_amount,
                precio_unt,
                invoice_detail_id,
                odoo_product_id,
                invoice_id,
                product_sku,
                product_name,
                operational_cost,
                standard_cost_snapshot
            FROM forum_his_invoice_detail
            WHERE invoice_id = ANY(%s)
        """
        cursor.execute(query, (invoice_ids,))
        return cursor.fetchall()

    @api.model
    def _sql_record_exists(self, table_name, record_id):
        """
        Verificar existencia de un registro en la BD de Odoo vía SQL directo.

        Este método evita depender del ORM para validar IDs críticos.
        """
        # Bloque: retorno temprano si el ID no es válido.
        if not record_id:
            return False

        # Bloque: control de tablas permitidas para evitar SQL inseguro.
        allowed_tables = {
            'res_partner',
            'product_product',
            'account_journal',
            'res_company',
        }
        if table_name not in allowed_tables:
            _logger.error("Tabla no permitida en verificación SQL: %s", table_name)
            return False

        # Bloque: ejecución SQL directa sobre la BD actual de Odoo.
        query = f"SELECT 1 FROM {table_name} WHERE id = %s LIMIT 1"
        self.env.cr.execute(query, (record_id,))
        return bool(self.env.cr.fetchone())

    def _historic_record_exists(self, cursor, table_name, record_id):
        """
        Verificar existencia de un registro en la BD histórica vía SQL directo.

        Se usa para validar IDs que vienen del histórico en la BD configurada.
        """
        # Bloque: retorno temprano si el ID no es válido.
        if not record_id:
            return False

        # Bloque: control de tablas permitidas para evitar SQL inseguro.
        allowed_tables = {
            'res_partner',
            'product_product',
            'account_journal',
            'res_company',
        }
        if table_name not in allowed_tables:
            _logger.error("Tabla no permitida en histórico: %s", table_name)
            return False

        # Bloque: ejecución SQL directa sobre la BD histórica.
        query = f"SELECT 1 FROM {table_name} WHERE id = %s LIMIT 1"
        cursor.execute(query, (record_id,))
        return bool(cursor.fetchone())

    def _mark_historic_invoices_processed(self, cursor, invoice_ids):
        """
        Marcar facturas históricas como procesadas.

        Este método actualiza el flag procesado para evitar reprocesamientos.
        """
        # Bloque: retorno temprano si no hay facturas.
        if not invoice_ids:
            return

        # Bloque: actualización masiva por lista de IDs.
        query = """
            UPDATE forum_his_invoice
            SET procesado = TRUE
            WHERE invoice_id = ANY(%s)
        """
        cursor.execute(query, (invoice_ids,))

    @api.model
    def _cron_import_historic_invoices(self, line_limit=None):
        """
        Cron de importación de facturas históricas.

        Este método procesa facturas pendientes por lotes, construye líneas con
        datos obligatorios derivados del producto y marca el histórico como procesado.
        """
        # Bloque: obtención del límite desde parámetros si no se recibe uno explícito.
        if line_limit is None:
            param_value = self.env['ir.config_parameter'].sudo().get_param(
                'forum_historico.line_limit',
                default='5000',
            )
            line_limit = self._safe_int(param_value)

        # Bloque: normalización del límite de líneas a procesar.
        line_limit = line_limit or 0

        # Bloque: conexión a la base histórica con cursor tipo diccionario.
        connection = self._get_historic_db_connection()
        if not connection:
            return
        cursor = connection.cursor(cursor_factory=extras.RealDictCursor)

        # Bloque: lectura de facturas pendientes respetando el límite de líneas.
        invoice_rows = self._fetch_pending_historic_invoices(cursor, line_limit)
        if not invoice_rows:
            connection.close()
            return

        # Bloque: preparación de IDs para lecturas masivas.
        invoice_ids = [row['invoice_id'] for row in invoice_rows]

        # Bloque: lectura masiva de líneas asociadas a las facturas.
        line_rows = self._fetch_historic_invoice_lines(cursor, invoice_ids)

        # Bloque: agrupación de líneas por factura.
        lines_by_invoice = defaultdict(list)
        for line in line_rows:
            lines_by_invoice[line['invoice_id']].append(line)
        # Bloque: caches de existencia para validaciones SQL directas.
        partner_exists_cache = {}
        product_exists_cache = {}
        journal_exists_cache = {}
        company_exists_cache = {}

        # Bloque: cacheo de registros Odoo para evitar lecturas repetidas.
        partners = {}
        journals = {}
        companies = {}

        # Bloque: cacheo global de productos para evitar búsquedas repetidas.
        product_model = self.env['product.product'].sudo()
        products = {}

        # Bloque: contadores y listas para auditoría de resultados.
        created_invoice_ids = []
        skipped_invoices = []
        failed_invoices = []
        # Bloque: cache de configuración por compañía.
        config_cache = {}
        config_model = self.env['config.default.historico'].sudo()

        # Bloque: construcción de valores de facturas y líneas.
        move_vals_list = []
        for row in invoice_rows:
            # Bloque: obtención y validación de IDs base.
            invoice_id = row.get('invoice_id')
            partner_id = self._safe_int(row.get('odoo_partner_id'))
            journal_id = self._safe_int(row.get('odoo_journal_id'))
            company_id = self._safe_int(row.get('odoo_company_id'))
            # Bloque: obtención de configuración por compañía.
            if company_id not in config_cache:
                config_cache[company_id] = config_model.get_config_for_company(company_id)
            config = config_cache.get(company_id)

            # Bloque: validación de existencia de partner vía SQL directo (Odoo e histórico).
            if partner_id not in partner_exists_cache:
                historic_exists = self._historic_record_exists(cursor, 'res_partner', partner_id)
                odoo_exists = self._sql_record_exists('res_partner', partner_id)
                partner_exists_cache[partner_id] = (historic_exists, odoo_exists)
            historic_partner_exists, odoo_partner_exists = partner_exists_cache.get(
                partner_id,
                (False, False),
            )
            original_partner_id = partner_id
            if not odoo_partner_exists:
                reason = "partner inválido"
                if historic_partner_exists:
                    reason = "partner existe en histórico pero no en Odoo"
                # Bloque: usar partner por defecto si está configurado.
                if config and config.default_partner_id:
                    partner_id = config.default_partner_id.id
                    partners[partner_id] = config.default_partner_id
                    _logger.info(
                        "Partner %s no existe, se usa default %s en factura %s.",
                        original_partner_id,
                        partner_id,
                        invoice_id,
                    )
                else:
                    _logger.warning(
                        "Factura %s omitida: %s (%s -> %s).",
                        invoice_id,
                        reason,
                        row.get('odoo_partner_id'),
                        original_partner_id,
                    )
                    skipped_invoices.append(f"{invoice_id} ({reason})")
                    continue
            if partner_id not in partners:
                # Bloque: cacheo del partner desde Odoo por ID validado.
                partners[partner_id] = self.env['res.partner'].sudo().browse(partner_id)

            # Bloque: validación de existencia de journal vía SQL directo (Odoo e histórico).
            if journal_id not in journal_exists_cache:
                historic_exists = self._historic_record_exists(cursor, 'account_journal', journal_id)
                odoo_exists = self._sql_record_exists('account_journal', journal_id)
                journal_exists_cache[journal_id] = (historic_exists, odoo_exists)
            historic_journal_exists, odoo_journal_exists = journal_exists_cache.get(
                journal_id,
                (False, False),
            )
            if not odoo_journal_exists:
                reason = "journal inválido"
                if historic_journal_exists:
                    reason = "journal existe en histórico pero no en Odoo"
                # Bloque: fallback a journal por defecto si está configurado.
                if config and config.default_journal_id:
                    journals[journal_id] = config.default_journal_id
                    journal_id = config.default_journal_id.id
                    _logger.info(
                        "Journal %s no existe, se usa default en factura %s.",
                        row.get('odoo_journal_id'),
                        invoice_id,
                    )
                else:
                    _logger.warning(
                        "Factura %s omitida: %s (%s -> %s).",
                        invoice_id,
                        reason,
                        row.get('odoo_journal_id'),
                        journal_id,
                    )
                    skipped_invoices.append(f"{invoice_id} ({reason})")
                    continue
            if journal_id not in journals:
                # Bloque: cacheo del journal desde Odoo por ID validado.
                journals[journal_id] = self.env['account.journal'].sudo().browse(journal_id)

            # Bloque: validación de existencia de company vía SQL directo (Odoo e histórico).
            if company_id not in company_exists_cache:
                historic_exists = self._historic_record_exists(cursor, 'res_company', company_id)
                odoo_exists = self._sql_record_exists('res_company', company_id)
                company_exists_cache[company_id] = (historic_exists, odoo_exists)
            historic_company_exists, odoo_company_exists = company_exists_cache.get(
                company_id,
                (False, False),
            )
            if not odoo_company_exists:
                reason = "company inválida"
                if historic_company_exists:
                    reason = "company existe en histórico pero no en Odoo"
                # Bloque: fallback a compañía por defecto si está configurada.
                if config and config.default_company_id:
                    companies[company_id] = config.default_company_id
                    company_id = config.default_company_id.id
                    _logger.info(
                        "Company %s no existe, se usa default en factura %s.",
                        row.get('odoo_company_id'),
                        invoice_id,
                    )
                else:
                    _logger.warning(
                        "Factura %s omitida: %s (%s -> %s).",
                        invoice_id,
                        reason,
                        row.get('odoo_company_id'),
                        company_id,
                    )
                    skipped_invoices.append(f"{invoice_id} ({reason})")
                    continue
            if company_id not in companies:
                # Bloque: cacheo de la compañía desde Odoo por ID validado.
                companies[company_id] = self.env['res.company'].sudo().browse(company_id)

            # Bloque: determinación de tipo de factura.
            move_type = 'out_invoice'
            if row.get('invoice_ticket_count') == -1:
                move_type = 'out_refund'

            # Bloque: preparación de líneas con datos derivados del producto.
            invoice_lines = []
            for line in lines_by_invoice.get(invoice_id, []):
                product_id = self._safe_int(line.get('odoo_product_id'))
                # Bloque: validación de existencia de producto vía SQL directo (Odoo e histórico).
                if product_id not in product_exists_cache:
                    historic_exists = self._historic_record_exists(cursor, 'product_product', product_id)
                    odoo_exists = self._sql_record_exists('product_product', product_id)
                    product_exists_cache[product_id] = (historic_exists, odoo_exists)
                historic_product_exists, odoo_product_exists = product_exists_cache.get(
                    product_id,
                    (False, False),
                )
                if not odoo_product_exists:
                    reason = "producto inválido"
                    if historic_product_exists:
                        reason = "producto existe en histórico pero no en Odoo"
                    # Bloque: usar producto por defecto si está configurado.
                    if config and config.default_product_id:
                        products[product_id] = config.default_product_id
                        _logger.info(
                            "Producto %s no existe, se usa default en factura %s.",
                            line.get('odoo_product_id'),
                            invoice_id,
                        )
                    else:
                        _logger.warning(
                            "Línea %s omitida: %s en factura %s.",
                            line.get('invoice_detail_id'),
                            reason,
                            invoice_id,
                        )
                        continue
                # Bloque: obtención segura del producto desde cache global.
                if product_id not in products:
                    products[product_id] = product_model.browse(product_id)
                product = products.get(product_id)

                # Bloque: impuestos según configuración del producto y compañía.
                product_in_company = product.with_company(company_id)
                taxes = product_in_company.taxes_id.filtered(
                    lambda t: t.company_id.id == company_id
                )
                # Bloque: aplicar impuestos por defecto si no hay impuestos configurados.
                if not taxes and config and config.default_tax_ids:
                    taxes = config.default_tax_ids.filtered(
                        lambda t: t.company_id.id == company_id
                    )

                # Bloque: cuenta de ingreso desde producto o categoría.
                income_account = (
                    product_in_company.property_account_income_id
                    or product_in_company.categ_id.property_account_income_categ_id
                )

                # Bloque: valores de línea basados en configuración del producto.
                line_vals = {
                    'product_id': product_in_company.id,
                    'name': product_in_company.display_name,
                    'quantity': line.get('invoice_detail_amount') or 0.0,
                    'price_unit': line.get('precio_unt') or 0.0,
                    'product_uom_id': product_in_company.uom_id.id,
                    'tax_ids': [(6, 0, taxes.ids)],
                }
                if income_account:
                    line_vals['account_id'] = income_account.id

                # Bloque: copia de campos de migración desde el histórico (si existen en la BD).
                # x_mig_product_tags_snapshot, x_mig_price_group_* NO se cargan por decisión de negocio.
                if line.get('product_sku') is not None:
                    line_vals['x_mig_product_sku'] = line.get('product_sku') or ''
                if line.get('product_name') is not None:
                    line_vals['x_mig_product_name'] = line.get('product_name') or ''
                try:
                    if line.get('operational_cost') is not None:
                        line_vals['x_mig_operational_cost'] = float(line.get('operational_cost'))
                except (TypeError, ValueError):
                    pass
                try:
                    if line.get('standard_cost_snapshot') is not None:
                        line_vals['x_mig_standard_cost_snapshot'] = float(line.get('standard_cost_snapshot'))
                except (TypeError, ValueError):
                    pass

                invoice_lines.append((0, 0, line_vals))

            # Bloque: omitir facturas sin líneas válidas.
            if not invoice_lines:
                _logger.warning("Factura %s omitida: sin líneas válidas.", invoice_id)
                skipped_invoices.append(f"{invoice_id} (sin líneas válidas)")
                continue

            # Bloque: valores finales de la factura.
            move_vals = {
                'move_type': move_type,
                'partner_id': partner_id,
                'journal_id': journal_id,
                'company_id': company_id,
                'invoice_date': row.get('invoice_local_date'),
                'invoice_line_ids': invoice_lines,
                'x_mig_source_document_id': invoice_id,
            }
            move_vals_list.append(move_vals)

        # Bloque: creación masiva de facturas con fallback por errores.
        if move_vals_list:
            try:
                created_moves = self.sudo().create(move_vals_list)
                created_invoice_ids = created_moves.mapped('x_mig_source_document_id')
                for created_id in created_invoice_ids:
                    _logger.info("Factura %s creada correctamente.", created_id)
                try:
                    created_moves.with_context(dont_send_to_dgi=True).action_post()
                except Exception as post_error:
                    _logger.error(
                        "Error al confirmar facturas creadas: %s",
                        str(post_error),
                    )
            except Exception as error:
                _logger.error(
                    "Error en creación masiva, se intentará por factura. Detalle: %s",
                    str(error),
                )
                created_invoice_ids = []
                for move_vals in move_vals_list:
                    try:
                        move = self.sudo().create(move_vals)
                        created_invoice_ids.append(move_vals['x_mig_source_document_id'])
                        _logger.info(
                            "Factura %s creada correctamente.",
                            move_vals.get('x_mig_source_document_id'),
                        )
                        try:
                            move.with_context(dont_send_to_dgi=True).action_post()
                        except Exception as post_error:
                            _logger.error(
                                "Factura %s no pudo confirmarse: %s",
                                move_vals.get('x_mig_source_document_id'),
                                str(post_error),
                            )
                    except Exception as line_error:
                        _logger.error(
                            "Factura %s no creada. Detalle: %s",
                            move_vals.get('x_mig_source_document_id'),
                            str(line_error),
                        )
                        failed_invoices.append(
                            f"{move_vals.get('x_mig_source_document_id')} (error creación)"
                        )

        # Bloque: actualización de estado procesado en el histórico.
        if created_invoice_ids:
            self._mark_historic_invoices_processed(cursor, created_invoice_ids)
            connection.commit()

        # Bloque: cierre de conexión externa.
        connection.close()

        # Bloque: resumen para log y notificación al usuario.
        def _format_list(items, max_items=50):
            # Bloque: limitar el tamaño del mensaje para evitar sobrecarga en logs.
            if len(items) <= max_items:
                return ', '.join(items)
            return ', '.join(items[:max_items]) + f", ... (+{len(items) - max_items})"

        created_text = _format_list([str(item) for item in created_invoice_ids])
        skipped_text = _format_list(skipped_invoices + failed_invoices)

        _logger.info(
            "Resultado carga histórico: creadas=%s | omitidas=%s",
            len(created_invoice_ids),
            len(skipped_invoices) + len(failed_invoices),
        )
        if created_text:
            _logger.info("Facturas creadas: %s", created_text)
        if skipped_text:
            _logger.info("Facturas omitidas: %s", skipped_text)

        # Bloque: notificación en UI con resumen de la ejecución del cron.
        message = (
            "Carga histórico finalizada. "
            f"Creadas: {len(created_invoice_ids)}. "
            f"Omitidas: {len(skipped_invoices) + len(failed_invoices)}. "
        )
        if created_text:
            message += f"Creadas: {created_text}. "
        if skipped_text:
            message += f"Omitidas: {skipped_text}."
        notify_method = getattr(self.env.user, 'notify_info', None)
        if callable(notify_method):
            notify_method(message=message, sticky=False)
        else:
            _logger.warning(
                "No se pudo notificar al usuario (notify_info no disponible). "
                "Resumen: %s",
                message,
            )

