#-*- coding: utf-8 -*-

import logging
import os
import csv
import tempfile
import base64
from odoo.exceptions import UserError
from odoo import api, fields, models, _, SUPERUSER_ID

_logger = logging.getLogger(__name__)

class ImportICTProduct(models.TransientModel):
    _name = "wizard.import.ict.product"
    _description = """
    This wizard helps to choose file which will going to import ICT lines from csv files
    """
    file_data = fields.Binary('CSV File')
    file_name = fields.Char('File Name')

    def import_button(self):
        if not self.csv_validator(self.file_name):
            raise UserError(_("The file must have an extention .csv"))
        file_path = tempfile.gettempdir()+'/file.csv'
        data = self.file_data
        f = open(file_path,'wb')
        f.write(base64.b64decode(data))
        #f.write(data.decode('base64'))
        f.close() 
        archive = csv.DictReader(open(file_path))

        ict_id = self.env.context.get("active_id", False)
        ict = self.env['setu.intercompany.transfer'].browse(ict_id)
        transfer_type = ict and ict.transfer_type or self.env.context.get('transfer_type', "")
        product_obj = self.env['product.product']
        intercompany_line_obj = self.env['setu.intercompany.transfer.line']
        
        archive_lines = []
        for line in archive:
            archive_lines.append(line)
            
        self.valid_columns_keys(archive_lines)
        self.valid_product_code(archive_lines, product_obj)

        if transfer_type == "inter_company":
            self.valid_prices(archive_lines)

        cont = 0
        for line in archive_lines:
            cont += 1
            price_unit = 0
            code = str(line.get('code',"")).strip()
            product_id = product_obj.search([('default_code','=',code)])
            if not product_id:
                raise UserError("Product %s not found", code)
            quantity = line.get('quantity',0)
            if transfer_type == "inter_company":
                price_unit = self.get_valid_price(line.get('price',""),cont)

            line = intercompany_line_obj.search([('product_id','=',product_id.id), ('intercompany_transfer_id','=',ict_id)])
            if line:
                vals = {'quantity': float(quantity)}
                if transfer_type == "inter_company":
                    if price_unit:
                        vals.update({'unit_price': price_unit })
                    else:
                        line.product_id_change()
                line.write(vals)
                continue

            vals = {
                'intercompany_transfer_id': ict_id,
                'product_id': product_id.id,
                'quantity': float(quantity),
            }
            if transfer_type == "inter_company":
                vals.update({'unit_price': price_unit})

            line = intercompany_line_obj.create(vals)
            if not price_unit and transfer_type == "inter_company":
                line.product_id_change()

        return {'type': 'ir.actions.act_window_close'}

    @api.model
    def valid_prices(self, archive_lines):
        cont = 0
        for line in archive_lines:
            cont += 1
            price = line.get('price',"")
            if not price:
                continue

            price = price.replace("$","").replace(",",".")
            try:
                price_float = float(price)
            except:
                raise UserError('The price of the product in the %s line, is not properly formatted.  Suitable formats, example: "$ 100.00" - "100.00" - "100"'%cont)
        return True

    @api.model
    def get_valid_price(self, price, cont):
        if not price:
            return False
        if price != "":
            price = price.replace("$","").replace(",",".")
        try:
            price_float = float(price)
            return price_float
        except:
            raise UserError('The price of the product in the %s line, is not properly formatted. Suitable formats, example: "$ 100.00" - "100.00" - "100"'%cont)
        return False
    
    @api.model
    def valid_product_code(self, archive_lines, product_obj):
        cont=0
        for line in archive_lines:
            cont += 1
            code = str(line.get('code',"")).strip()
            product_id = product_obj.search([('default_code','=',code)])
            if len(product_id)>1:
                raise UserError("Multiple products found with this code %s, it must be unique."%code)
            if not product_id:
                raise UserError("Product not found with this code %s."%code)
            
    @api.model
    def valid_columns_keys(self, archive_lines):
        columns = archive_lines[0].keys()
        text = "The csv file must contain the following columns: code & quantity."
        text2 = text
        if not 'code' in columns:
            text +="\n[ code ]"
        if not 'quantity' in columns:
            text +="\n[ quantity ]"
        if text !=text2:
            raise UserError(text)
        return True
            
    @api.model
    def csv_validator(self, xml_name):
        name, extension = os.path.splitext(xml_name)
        return True if extension == '.csv' else False

    def wizard_view(self):
        action = self.env.ref('setu_intercompany_transaction.action_wizard_import_ict_product').sudo().read()[0]
        form_view_id = self.env.ref('setu_intercompany_transaction.form_wizard_import_ict_lines').id
        action['views'] = [(form_view_id, "form")]
        return action