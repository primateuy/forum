import os
import csv
import tempfile
import base64
from dateutil.relativedelta import relativedelta
from odoo import fields, models, api, _
from odoo.exceptions import UserError


class SaleForecasetAutoImportWizard(models.TransientModel):
    _name = 'sale.forecast.auto.import.wizard'
    _description = "Auto Import or Export Sales Forecast"

    @api.onchange('process_type', 'import_process_by')
    def _compute_is_auto_import_export(self):
        is_auto_import_export = False
        if self.process_type:
            if self.process_type == 'export' or (self.process_type == 'import' and
                                                 self.import_process_by == 'auto_import'):
                is_auto_import_export = True
        self.is_auto_import_export = is_auto_import_export

    process_type = fields.Selection([('import', 'Import'), ('export', 'Export')],
                                    string='Process Type')
    import_process_by = fields.Selection([('file_import', 'File Import'), ('auto_import', 'Auto Create')],
                                         string='Import Forecast By')
    import_file_attachment = fields.Binary('Import File')
    export_file = fields.Binary('Export File')
    export_file_name = fields.Char('Export File Name')
    file_name = fields.Char('File Name')
    create_forecast_sales_from = fields.Selection([('history_sales', 'History Sales'),
                                                   ('forecast_sales', 'Forecast Sales')],
                                                  string="Create Sales Forecast from", default='history_sales')
    auto_forecast_growth = fields.Float('Growth', help="Add Percentage Value If in forecast needed")
    target_period_ids = fields.Many2many("reorder.fiscalperiod", 'target_fiscal_period_rel',
                                         'wizard_id', 'target_period_id',
                                         string="Target Period")
    source_period_id = fields.Many2one("reorder.fiscalperiod", string="From Period")
    destination_period_id = fields.Many2one("reorder.fiscalperiod", string="To Period")
    product_ids = fields.Many2many("product.product", 'sale_forecast_wiz_product_rel', 'sale_forecast_wiz_id', 'product_id', string="Products")
    products_ids = fields.Many2many("product.product", 'sale_forecast_wizard_product_rel', 'sale_forecast_wizard_id', 'products_id',
                                    string="Products",
                                    compute="_compute_products_ids")
    product_category_ids = fields.Many2many('product.category', string="Product Category")
    warehouse_ids = fields.Many2many("stock.warehouse", 'sale_forecast_wiz_warehouse_rel', 'sale_forecast_wiz_id', 'warehouse_id', string="Warehouses")
    warehouses_ids = fields.Many2many("stock.warehouse", 'sale_forecast_wizard_warehouses_rel', 'sale_forecast_wizard_id',
                                    'warehouses_id',
                                    string="Warehouses",
                                    compute="_compute_warehouses_ids")
    company_ids = fields.Many2many("res.company", string="Companies")
    is_auto_import_export = fields.Boolean('Is Auto Import or Export Process', default=False,
                                           compute='_compute_is_auto_import_export')
    forecast_sales_of = fields.Selection([('normal_forecast', 'Normal Forecast'),
                                          ('seasonal_forecast', 'Seasonal Forecast')],
                                         string="Forecast Sale of")

    # @api.onchange('product_category_ids')
    # def onchange_product_category_id(self):
    #     if self.product_category_ids:
    #         return {'domain': {'product_ids': [('categ_id', 'child_of', self.product_category_ids.ids)]}}

    @api.depends('product_category_ids')
    def _compute_products_ids(self):
        for record in self:
            if record.product_category_ids:
                products = self.env['product.product'].search(
                    [('categ_id', 'child_of', record.product_category_ids.ids)])
                record.products_ids = products if products else False
            else:
                products = self.env['product.product'].search([])
                record.products_ids = products if products else False

    # @api.onchange('company_ids')
    # def onchange_company_id(self):
    #     if self.company_ids:
    #         return {'domain': {'warehouse_ids': [('company_id', 'child_of', self.company_ids.ids)]}}

    @api.depends('company_ids')
    def _compute_warehouses_ids(self):
        for record in self:
            if record.company_ids:
                warehouses = self.env['stock.warehouse'].search(
                    [('company_id', 'child_of', record.company_ids.ids)])
                record.warehouses_ids = warehouses if warehouses else False
            else:
                warehouses = self.env['stock.warehouse'].search([])
                record.warehouses_ids = warehouses if warehouses else False

    @api.onchange('process_type', 'import_process_by')
    def onchange_process_type(self):
        if self.process_type == 'export':
            self.import_process_by = False

        self.import_file_attachment = False
        self.create_forecast_sales_from = False
        self.forecast_sales_of = False
        self.auto_forecast_growth = 0.0
        self.source_period_id = False
        self.destination_period_id = False
        self.target_period_ids = False
        self.product_category_ids = False
        self.product_ids = False
        self.company_ids = False
        self.warehouse_ids = False

    @api.model
    def default_get(self, fields):
        rec = super(SaleForecasetAutoImportWizard, self).default_get(fields)
        if self._context.get('reorder_import_foreacast', False):
            rec.update({'process_type': 'import', 'import_process_by': 'file_import'})
        return rec

    @api.model
    def csv_validator(self, xml_name):
        name, extension = os.path.splitext(xml_name)
        return True if extension == '.csv' else False

    @api.model
    def validating_column_header(self, file_headers, fiscal_period_header):
        not_included_column = ''
        not_fiscal_period = ''
        fiscal_period_dict = {}
        fiscal_period_obj = self.env['reorder.fiscalperiod']

        if 'Product' not in file_headers:
            not_included_column += "\n[ Product ]"
        if 'Warehouse' not in file_headers:
            not_included_column += "\n[ Warehouse ]"
        if not_included_column:
            raise UserError("The csv file must contain the following columns:" + not_included_column)

        for header in fiscal_period_header:
            fiscal_period_id = fiscal_period_obj.search([('code', '=', header)])
            if not fiscal_period_id:
                not_fiscal_period += "\n[ %s ]" % header
            else:
                fiscal_period_dict.update({header: fiscal_period_id.id})
        if not_fiscal_period:
            raise UserError("The following Fiscal Period are not configure or add wrong column: " + not_fiscal_period)
        return fiscal_period_dict

    def delete_missing_forecast_reorder_procurement(self, products, warehouses, periods):
        non_forecast_sale_obj = self.env['advance.reorder.non.product.forecast']
        active_id = self._context.get('active_id')
        domain = [('product_id', 'in', products), ('warehouse_id', 'in', warehouses),
                  ('period_id', 'in', periods)]

        if self._context.get('active_model') == 'advance.reorder.orderprocess':
            domain.append(('reorder_process_id', '=', active_id))
        elif self._context.get('active_model') == 'advance.procurement.process':
            domain.append(('procurement_process_id', '=', active_id))

        missing_forecast_ids = non_forecast_sale_obj.search(domain)
        missing_forecast_ids and missing_forecast_ids.unlink()
        return True

    def validating_file_data(self, file_lines, fiscal_period_header, fiscal_period_dict):
        product_dict, warehouse_dict = {}, {}
        file_data, warning_lines, not_product, not_warehouse, multi_product = [], [], [], [], []
        line_count = 0
        product_obj = self.env['product.product']
        warehouse_obj = self.env['stock.warehouse']

        for line in file_lines:
            line_count += 1
            default_code = line.get('Product', '')
            if not default_code:
                warning_lines.append(line_count)
                continue

            warehouse_name = line.get('Warehouse', '')
            if not warehouse_name:
                warning_lines.append(line_count)
                continue

            if not product_dict.get(default_code) and (default_code not in not_product or
                                                       default_code not in multi_product):
                product_id = product_obj.search([('default_code', '=', default_code)], limit=1)
                if not product_id:
                    not_product.append(default_code)
                if len(product_id) > 1:
                    multi_product.append(default_code)
                product_dict.update({default_code: product_id.id})

            if not warehouse_dict.get(warehouse_name) and warehouse_name not in not_warehouse:
                warehouse_id = warehouse_obj.search([('name', '=', warehouse_name)])
                if not warehouse_id:
                    not_warehouse.append(warehouse_name)

                warehouse_dict.update({warehouse_name: warehouse_id.id})

            for header in fiscal_period_header:
                forecast_qty = line.get(header) and float(line.get(header, 0.0))
                if forecast_qty:
                    file_data.append([product_dict.get(default_code), warehouse_dict.get(warehouse_name),
                                      fiscal_period_dict.get(header), forecast_qty])
        warning_string = ''
        if warning_lines:
            warning_string += "Product Internal Reference or Warehouse is not set in file in row : %s \n\n" % \
                              str(warning_lines)
        if not_product:
            warning_string += "Product Internal Reference %s are not configure in system \n\n" % str(not_product)
        if multi_product:
            warning_string += "Multiple products found with this code %s, it must be unique\n\n" % str(multi_product)
        if not_warehouse:
            warning_string += "Warehouse %s are not configure in system" % str(not_warehouse)
        if warning_string:
            raise UserError(warning_string)
        if self._context.get('reorder_import_foreacast', False):
            self.delete_missing_forecast_reorder_procurement(list(product_dict.values()),
                                                             list(warehouse_dict.values()),
                                                             list(fiscal_period_dict.values()))
        return file_data

    def import_file_sale_forecast(self):
        forecast_sale_obj = self.env['forecast.product.sale']
        if not self.csv_validator(self.file_name):
            raise UserError(_("The file must have an extension .csv"))
        file_path = tempfile.gettempdir() + '/sale_forecast_import.csv'
        data = self.import_file_attachment
        f = open(file_path, 'wb')
        f.write(base64.b64decode(data))
        f.close()
        file_reader = csv.DictReader(open(file_path))
        file_lines = []
        for line in file_reader:
            file_lines.append(line)
        if not file_lines:
            return True
        file_headers = list(file_lines[0].keys())
        fiscal_period_header = file_headers[2:]
        if not fiscal_period_header:
            raise UserError("Fiscal Period is not found as header in file.\n"
                            "Please configure header and try again to import file")
        fiscal_period_dict = self.validating_column_header(file_headers, fiscal_period_header)
        file_data = self.validating_file_data(file_lines, fiscal_period_header, fiscal_period_dict)
        for data in file_data:
            if len(data) == 4:
                forecast_sale_id = forecast_sale_obj.search([('product_id', '=', data[0]),
                                                             ('warehouse_id', '=', data[1]),
                                                             ('period_id', '=', data[2])])
                if forecast_sale_id:
                    forecast_sale_id.write({'forecast_qty': data[3]})
                else:
                    forecast_vals = {
                        'product_id': data[0],
                        'warehouse_id': data[1],
                        'period_id': data[2],
                        'forecast_qty': data[3]
                    }
                    obj = forecast_sale_obj.create(forecast_vals)
                    query = f"""
                    update forecast_product_sale
                    set actual_sale_qty = 0
                    where id = {obj.id}
                    """
                    self._cr.execute(query)
        return True

    def get_history_sale_auto_forecast_sale(self, company_ids, start_date, end_date,
                                            target_period_ids, warehouse_ids, category_ids,
                                            product_ids, auto_forecast_growth):
        fiscal_period_obj = self.env['reorder.fiscalperiod']
        forecast_sale_data = []
        difference_days = (end_date - start_date).days
        query = """Select * from get_products_sales_warehouse_group_wise
                   ('%s','%s','%s', '%s', '%s', '%s')""" \
                % (set(company_ids), set(product_ids), set(category_ids), set(warehouse_ids),
                   str(start_date), str(end_date))
        self._cr.execute(query)
        get_stock_data = self._cr.dictfetchall() or []
        for stock_data in get_stock_data:
            warehouse_id = stock_data.get('warehouse_id')
            product_id = stock_data.get('product_id')
            total_sales = stock_data.get('total_sales')
            total_sales = total_sales / difference_days
            for target_period_id in target_period_ids:
                avg_sales = 0.0
                target_period = fiscal_period_obj.browse(target_period_id)
                days = (target_period.fpenddate - target_period.fpstartdate).days + 1
                avg_sales = total_sales * days
                if auto_forecast_growth:
                    avg_sales = avg_sales + (avg_sales * auto_forecast_growth)
                forecast_sale_data.append([product_id, warehouse_id, target_period_id, avg_sales])
        return forecast_sale_data

    def get_forecast_sale_auto_forecast(self, product_ids, warehouse_ids, fiscal_period_ids,
                                        target_period_ids, auto_forecast_growth):
        forecast_sale_data = []
        forecast_sale_obj = self.env['forecast.product.sale']
        fiscal_period_obj = self.env['reorder.fiscalperiod']
        forecast_sale_ids = forecast_sale_obj.search([('period_id', 'in', fiscal_period_ids),
                                                      ('warehouse_id', 'in', warehouse_ids),
                                                      ('product_id', 'in', product_ids)],
                                                     order='period_id, warehouse_id, product_id')
        total_forecast_sale = 0.0
        for warehouse_id in warehouse_ids:
            for product_id in product_ids:
                forecast_sales = forecast_sale_ids.filtered(lambda x: x.warehouse_id.id == warehouse_id and
                                                                      x.product_id.id == product_id)
                total_forecast_sale = sum(forecast_sales.mapped('forecast_qty')) or 0.0
                if not total_forecast_sale:
                    continue
                for target_period_id in target_period_ids:
                    avg_sales = 0.0
                    target_period = fiscal_period_obj.browse(target_period_id)
                    days = (target_period.fpenddate - target_period.fpstartdate).days + 1
                    avg_sales = total_forecast_sale / days
                    if auto_forecast_growth:
                        avg_sales = avg_sales + (avg_sales * auto_forecast_growth)
                    forecast_sale_data.append([product_id, warehouse_id, target_period_id, avg_sales])
        return forecast_sale_data

    def get_seasonal_forecast_auto_forecast(self, product_ids, warehouse_ids,
                                            target_period_ids, auto_forecast_growth):
        forecast_sale_data = []
        forecast_sale_obj = self.env['forecast.product.sale']
        fiscal_period_obj = self.env['reorder.fiscalperiod']
        forecast_sales = forecast_sale_obj.search([('warehouse_id', 'in', warehouse_ids),
                                                   ('product_id', 'in', product_ids)],
                                                  order='warehouse_id, product_id')
        for target_period_id in self.target_period_ids:
            start_date = target_period_id.fpstartdate - relativedelta(years=1)
            end_date = target_period_id.fpenddate - relativedelta(years=1)
            if end_date.month == 2 and end_date.year % 4 == 0:
                end_date = end_date + relativedelta(days=1)
            fiscal_period_id = fiscal_period_obj.search([('fpstartdate', '>=', start_date),
                                                         ('fpenddate', '<=', end_date)]).id
            if fiscal_period_id:
                forecast_sales_period = forecast_sales.filtered(lambda x: x.period_id.id == fiscal_period_id)
                for forecast_sale in forecast_sales_period:
                    forecast_qty = forecast_sale.forecast_qty
                    if auto_forecast_growth:
                        forecast_qty = forecast_qty + (forecast_qty * auto_forecast_growth)
                    forecast_sale_data.append([forecast_sale.product_id.id, forecast_sale.warehouse_id.id,
                                               target_period_id.id, forecast_qty])
        return forecast_sale_data

    def get_data_auto_forecast_sale(self):
        fiscal_period_obj = self.env['reorder.fiscalperiod']
        product_product_obj = self.env['product.product']
        stock_warehouse_obj = self.env['stock.warehouse']
        company_obj = self.env['res.company']
        product_category_obj = self.env['product.category']
        forecast_data = []
        get_sales_from = self.create_forecast_sales_from
        target_period_ids = self.target_period_ids.ids
        category_ids = self.product_category_ids.ids
        product_ids = self.product_ids.ids
        company_ids = self.company_ids.ids
        warehouse_ids = self.warehouse_ids.ids
        auto_forecast_growth = self.auto_forecast_growth and self.auto_forecast_growth / 100 or 0.0
        fiscal_period_ids = fiscal_period_obj.search([('fpstartdate', '>=', self.source_period_id.fpstartdate),
                                                      ('fpenddate', '<=', self.destination_period_id.fpenddate)]).ids
        if not company_ids:
            company_ids = company_obj.search([]).ids
        if not warehouse_ids:
            warehouse_ids = stock_warehouse_obj.search([('company_id', 'in', company_ids)]).ids
        if not category_ids:
            category_ids = product_category_obj.search([]).ids
        if not product_ids:
            product_ids = product_product_obj.search([('categ_id', 'in', category_ids), ('type', '=', 'product')]).ids
        if get_sales_from == 'history_sales':
            forecast_data = self.get_history_sale_auto_forecast_sale(company_ids, self.source_period_id.fpstartdate,
                                                                     self.destination_period_id.fpenddate,
                                                                     target_period_ids, warehouse_ids, category_ids,
                                                                     product_ids, auto_forecast_growth)
        elif get_sales_from == 'forecast_sales':
            if self.forecast_sales_of == 'seasonal_forecast':
                forecast_data = self.get_seasonal_forecast_auto_forecast(product_ids, warehouse_ids,
                                                                         target_period_ids,
                                                                         auto_forecast_growth)
            else:
                forecast_data = self.get_forecast_sale_auto_forecast(product_ids, warehouse_ids,
                                                                     fiscal_period_ids, target_period_ids,
                                                                     auto_forecast_growth)
        return forecast_data

    def import_auto_create_sale_forecast(self):
        forecast_sale_obj = self.env['forecast.product.sale']
        forecast_sale_data = {}
        if self.source_period_id.fpstartdate > self.destination_period_id.fpenddate:
            raise UserError("Source Period must be greater then Destination Period")
        forecast_sale_data = self.get_data_auto_forecast_sale()
        for data in forecast_sale_data:
            if len(data) == 4:
                forecast_sale_id = forecast_sale_obj.search([('product_id', '=', data[0]),
                                                             ('warehouse_id', '=', data[1]),
                                                             ('period_id', '=', data[2])])
                if forecast_sale_id:
                    forecast_sale_id.write({'forecast_qty': data[3]})
                else:
                    forecast_vals = {
                        'product_id': data[0],
                        'warehouse_id': data[1],
                        'period_id': data[2],
                        'forecast_qty': data[3]
                    }
                    # forecast_sale_obj.create(forecast_vals)
                    obj = forecast_sale_obj.create(forecast_vals)
                    query = f"""
                                        update forecast_product_sale
                                        set actual_sale_qty = 0
                                        where id = {obj.id}
                                        """
                    self._cr.execute(query)
        return True

    def action_auto_import_sale_forecast(self):
        # print('get_debugger')
        import_process = self.import_process_by
        if import_process == 'file_import':
            self.import_file_sale_forecast()
        elif import_process == 'auto_import':
            self.import_auto_create_sale_forecast()
        return True

    def get_export_data_forecast_sale(self, fiscal_period_ids):
        product_product_obj = self.env['product.product']
        stock_warehouse_obj = self.env['stock.warehouse']
        forecast_sale_obj = self.env['forecast.product.sale']
        domain = []
        forecast_sale_data = {}
        source_period = self.source_period_id
        destination_period = self.destination_period_id
        category_ids = self.product_category_ids.ids
        product_ids = self.product_ids.ids
        company_ids = self.company_ids.ids
        warehouse_ids = self.warehouse_ids.ids

        if source_period and destination_period:
            domain.append(('period_id', 'in', fiscal_period_ids.ids))
        if category_ids and not product_ids:
            product_ids = product_product_obj.search([('categ_id', 'in', category_ids), ('type', '=', 'product')]).ids
        product_ids and domain.append(('product_id', 'in', product_ids))
        if company_ids and not warehouse_ids:
            warehouse_ids = stock_warehouse_obj.search([('company_id', 'in', company_ids)]).ids
        warehouse_ids and domain.append(('warehouse_id', 'in', warehouse_ids))
        forecast_sale_ids = forecast_sale_obj.search(domain, order='period_id, warehouse_id, product_id')

        for sale in forecast_sale_ids:
            warehouse_id = sale.warehouse_id.name
            product_id = sale.product_id.id
            period_code = sale.period_id.code
            forecast_qty = round(sale.forecast_qty, 2)
            if forecast_sale_data.get(warehouse_id):
                if forecast_sale_data.get(warehouse_id).get(product_id):
                    if forecast_sale_data.get(warehouse_id).get(product_id).get(period_code):
                        previous_forecast_qty = forecast_sale_data.get(warehouse_id). \
                            get(product_id).get(period_code)
                        forecast_sale_data.get(warehouse_id).get(product_id).get(period_code). \
                            update(previous_forecast_qty + forecast_qty)
                    else:
                        forecast_sale_data.get(warehouse_id).get(product_id).update({period_code: forecast_qty})
                else:
                    forecast_sale_data.get(warehouse_id).update({product_id: {period_code: forecast_qty}})
            else:
                forecast_sale_data.update({warehouse_id: {product_id: {period_code: forecast_qty}}})
        return forecast_sale_data

    def get_export_data_normal_sale(self, fiscal_period_ids):
        product_product_obj = self.env['product.product']
        stock_warehouse_obj = self.env['stock.warehouse']
        company_obj = self.env['res.company']
        product_category_obj = self.env['product.category']
        forecast_sale_data = {}
        source_period = self.source_period_id
        destination_period = self.destination_period_id
        category_ids = self.product_category_ids.ids
        product_ids = self.product_ids.ids
        company_ids = self.company_ids.ids
        warehouse_ids = self.warehouse_ids.ids
        if not company_ids:
            company_ids = company_obj.search([]).ids
        if not warehouse_ids:
            warehouse_ids = stock_warehouse_obj.search([('company_id', 'in', company_ids)]).ids
        if not category_ids:
            category_ids = product_category_obj.search([]).ids
        if not product_ids:
            product_ids = product_product_obj.search([('categ_id', 'in', category_ids), ('type', '=', 'product')]).ids

        for fiscal_period_id in fiscal_period_ids:
            period_code = fiscal_period_id.code
            query = """Select * from get_stock_data('%s','%s','%s', '%s', 'sales', '%s', '%s')""" \
                    % (set(company_ids), set(product_ids), set(category_ids), set(warehouse_ids),
                       str(fiscal_period_id.fpstartdate), str(fiscal_period_id.fpenddate))
            self._cr.execute(query)
            get_stock_data = self._cr.dictfetchall() or []
            for stock_data in get_stock_data:
                warehouse_name = stock_data.get('warehouse_name')
                product_id = stock_data.get('product_id')
                product_qty = stock_data.get('product_qty')
                if forecast_sale_data.get(warehouse_name):
                    if forecast_sale_data.get(warehouse_name).get(product_id):
                        if forecast_sale_data.get(warehouse_name).get(product_id).get(period_code):
                            previous_product_qty = forecast_sale_data.get(warehouse_name). \
                                get(product_id).get(period_code)
                            forecast_sale_data.get(warehouse_name).get(product_id).get(period_code). \
                                update(previous_product_qty + product_qty)
                        else:
                            forecast_sale_data.get(warehouse_name).get(product_id).update({period_code: product_qty})
                    else:
                        forecast_sale_data.get(warehouse_name).update({product_id: {period_code: product_qty}})
                else:
                    forecast_sale_data.update({warehouse_name: {product_id: {period_code: product_qty}}})
        return forecast_sale_data

    def export_file_data(self, forecast_sale_data, fiscal_period_ids):
        product_product_obj = self.env['product.product']

        headers = ['Product', 'Warehouse']
        headers.extend(fiscal_period_ids.mapped('code'))

        csv_file = open('/tmp/Export_Forecast_Sale.csv', 'w+', newline='')
        writer = csv.DictWriter(csv_file, fieldnames=headers)
        writer.writeheader()
        for warehouse_name, values in forecast_sale_data.items():
            for product_id, sub_values in values.items():
                product_id = product_product_obj.browse(product_id)
                sub_values.update({'Product': product_id.default_code, 'Warehouse': warehouse_name})
                writer.writerow(sub_values)
        csv_file.close()

        file = open('/tmp/Export_Forecast_Sale.csv', 'rb')
        file.seek(0)
        file_data = base64.encodebytes(file.read())
        file.close()
        self.write({'export_file': file_data, 'export_file_name': 'Export_Forecast_Sale.csv'})
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/binary/download_document?model=sale.forecast.auto.import.wizard&field=export_file&id=%s&filename=%s' % (
                self.id, self.export_file_name),
            'target': 'self',
        }

    def action_auto_export_forecast_sale(self):
        fiscal_period_obj = self.env['reorder.fiscalperiod']
        forecast_sale_data, download_dict = {}, {}
        if self.source_period_id.fpstartdate > self.destination_period_id.fpenddate:
            raise UserError("Source Period must be greater then Destination Period")
        fiscal_period_ids = fiscal_period_obj.search([('fpstartdate', '>=', self.source_period_id.fpstartdate),
                                                      ('fpenddate', '<=', self.destination_period_id.fpenddate)])

        if self.create_forecast_sales_from == 'forecast_sales':
            forecast_sale_data = self.get_export_data_forecast_sale(fiscal_period_ids)
        elif self.create_forecast_sales_from == 'history_sales':
            forecast_sale_data = self.get_export_data_normal_sale(fiscal_period_ids)

        if forecast_sale_data:
            download_dict = self.export_file_data(forecast_sale_data, fiscal_period_ids)
        return download_dict
