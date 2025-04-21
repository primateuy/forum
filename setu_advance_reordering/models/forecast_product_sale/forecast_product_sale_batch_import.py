from odoo import fields, models, api
import os
import csv
import tempfile
import base64
import datetime


class ForecastProductSaleBatchImport(models.Model):
    _name = 'forecast.product.sale.batch.import'
    _description = "Import Sales Forecast in Batch"

    name = fields.Char("Name")
    # date = fields.Date("Date")
    user_id = fields.Many2one('res.users', "Responsible", default=lambda self: self.env.user)
    main_attachment_id = fields.Many2one('ir.attachment', string="File for Import")
    # main_attachment = fields.Binary("Attachment")
    # main_attachment_file_name = fields.Char("Attachment File Name")
    # warehouse_id = fields.Many2one('stock.warehouse', "Warehouse")
    # period_id = fields.Many2one('reorder.fiscalperiod', "Fiscal Period")
    state = fields.Selection([('draft', 'Draft'), ('in_progress', 'In progress'),
                              ('cancel', 'Cancel'), ('done', 'Done')],
                             string="State", default='draft')
    batch_import_line_ids = fields.One2many('forecast.batch.import.line', 'forecast_batch_import_id',
                                            string="Forecast Batch Import Line")
    per_attachment_lines = fields.Integer('Per Attachment Line')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            name = self.env['ir.sequence'].next_by_code('forecast.product.sale.batch.import')
            vals.update({'name': name})
        res = super(ForecastProductSaleBatchImport, self).create(vals_list)
        return res

    def create_forecast_batch_import_line(self, batch_import_id):
        batch_line_obj = self.env['forecast.batch.import.line']
        attachment_obj = self.env['ir.attachment']
        batch_import = self.browse(batch_import_id)
        per_lines = batch_import.per_attachment_lines

        today_date_time = datetime.datetime.today().strftime('%Y_%m_%d_%H_%M_%S')
        file_name, extension = os.path.splitext(batch_import.main_attachment_id.name)
        file_path = tempfile.gettempdir() + '/%s_%s%s' % (file_name, today_date_time, extension)

        data = batch_import.main_attachment_id
        f = open(file_path, 'wb')
        f.write(base64.b64decode(data))
        f.close()

        csvfile = open(file_path, 'r').readlines()
        f_no = 1
        header = csvfile[0]

        for i in range(len(csvfile)):
            sub_data = False
            if i % per_lines == 0:
                if not i == 0:
                    csv_data = [header] + csvfile[i:i + per_lines]
                else:
                    csv_data = csvfile[i:i + per_lines]
                sub_file_name = 'Sub_%s_%s_%s%s' % (file_name, f_no, today_date_time, extension)
                sub_file_path = tempfile.gettempdir() + '/' + sub_file_name
                open(sub_file_path, 'w+').writelines(csv_data)
                sub_file = open(sub_file_path, 'rb')
                sub_data = base64.b64encode(sub_file.read())
                sub_file.close()
                f_no += 1

            if sub_data:
                attachment_vals = {'name': sub_file_name,
                                   'type': 'binary',
                                   'datas': sub_data}

                sub_attachment_id = attachment_obj.create(attachment_vals)
                line_vals = {'sequence': f_no,
                             'sub_attachment_id': sub_attachment_id.id,
                             # 'sub_attachment': sub_data,
                             # 'sub_attachment_file_name': sub_file_name,
                             'forecast_batch_import_id': batch_import_id}
                batch_line_obj.create(line_vals)

        cron_id = self.env.ref('setu_advance_reordering.cron_process_batch_import_line')
        cron_id.write({'nextcall': datetime.datetime.now(),  # + datetime.timedelta(minutes=1),
                       'active': True, 'numbercall': 1,
                       'code': 'model.process_forecast_batch_import_line(%s)' % batch_import_id})
        return True

    def process_forecast_batch_import_line(self, batch_import_id):
        return True


class ForecastBatchImportLine(models.Model):
    _name = 'forecast.batch.import.line'
    _description = "Import Forecast Batch Line"

    forecast_batch_import_id = fields.Many2one('forecast.product.sale.batch.import',
                                               string="Forecast Batch Import")
    sequence = fields.Integer('Sequence')
    sub_attachment_id = fields.Many2one('ir.attachment', string="File")
    # sub_attachment = fields.Binary("Attachment")
    # sub_attachment_file_name = fields.Char("Attachment File Name")
    state = fields.Selection([('draft', 'Draft'), ('in_progress', 'In progress'),
                              ('cancel', 'Cancel'), ('done', 'Done')],
                             string="State", default='draft')
    done_date = fields.Datetime('Done Date')
