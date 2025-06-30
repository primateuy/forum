# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.

import tempfile
import binascii
import xlrd
from odoo.exceptions import ValidationError
from odoo import models, fields, exceptions, api, tools, _
import time
from datetime import date, datetime
import urllib
from collections import defaultdict
import itertools
import re
import io
import logging

_logger = logging.getLogger(__name__)

try:
    import csv
except ImportError:
    _logger.debug('Cannot `import csv`.')
try:
    import xlwt
except ImportError:
    _logger.debug('Cannot `import xlwt`.')
try:
    import cStringIO
except ImportError:
    _logger.debug('Cannot `import cStringIO`.')
try:
    import base64
except ImportError:
    _logger.debug('Cannot `import base64`.')


class InheritProductTemplate(models.Model):
    _inherit = 'product.product'

    dummy = fields.Char('dummy')
    imported_prod = fields.Boolean(string='Imported prod')


class product_template(models.Model):
    _inherit = 'product.template'
    _order = "uniq_id,name"

    uniq_id = fields.Char('Unique ID')
    dummy = fields.Char('dummy')

    def _create_variant_ids(self):
        if self._context.get('force_stop') == True:
            return True
        else:
            res = super(product_template, self)._create_variant_ids()
            return res


class gen_sale(models.TransientModel):
    _name = "gen.sale"
    _description = "Gen Sale"

    file = fields.Binary('File')
    filename=fields.Char(string="Filename")
    product_option = fields.Selection(
        [('create', 'Create Product With Variants'), ('update', 'Create/Update Product With Variants')],
        string='Option', required=True, default="create")
    product_search = fields.Selection(
        [('by_code', 'Search By Code'), ('by_name', 'Search By Name'), ('by_barcode', 'Search By Barcode')],
        string='Search Product', default='by_name')
    import_option = fields.Selection([('csv', 'CSV File'), ('xls', 'XLS File')], string='Select', default='csv')

    def check_splcharacter(self, test):
        string_check = re.compile('@')
        if (string_check.search(str(test)) == None):
            return False
        else:
            return True

    def create_img(self, image, product_id):
        prod = self.env['product.image'].create({
            'product_tmpl_id': product_id.id,
            'name': product_id.name,
            'image_1920': image
        })

    def create_var_img(self, image, product_id):
        prod = self.env['product.image'].create({
            'product_variant_id': product_id.id,
            'name': product_id.name,
            'image_1920': image
        })

    def create_product(self,values):
        dict_id ={}
        attribute_list = []
        product_tmpl_obj = self.env['product.template']
        product_obj = self.env['product.product']
        product_categ_obj = self.env['product.category']
        product_uom_obj = self.env['uom.uom']
        xml_ids = defaultdict(list)
        domain = [('model', '=', product_tmpl_obj._name), ('res_id', 'in', product_tmpl_obj.ids)]

        for cat in product_tmpl_obj:
            cat.uniq_id =values.get('u_id')
        if values.get('categ_id')=='':
            raise ValidationError(_('CATEGORY field can not be empty'))
        else:
            categ_id = product_categ_obj.search([('name','=',values.get('categ_id'))],limit=1)
            if not categ_id:
                # Crear la categoría automáticamente si no existe
                categ_id = product_categ_obj.create({'name': values.get('categ_id')})
                _logger.info('Created new category: %s', values.get('categ_id'))
        
        if values.get('type') == 'Consumable':
            categ_type ='consu'
        elif values.get('type') == 'Service':
            categ_type ='service'
        elif values.get('type') == 'Storable Product':
            categ_type ='product'
        else:
            categ_type = 'product'
        
        if values.get('uom_id')=='':
            uom_id = 1
        else:
            uom_search_id  = product_uom_obj.search([('name','=',values.get('uom_id'))])
            if not uom_search_id:
                raise ValidationError(_('UOM %s not found.' %values.get('uom_id') ))
            uom_id = uom_search_id.id
        
        if values.get('uom_po_id')=='':
            uom_po_id = 1
        else:
            uom_po_search_id  = product_uom_obj.search([('name','=',values.get('uom_po_id'))])
            if not uom_po_search_id:
                raise ValidationError(_('Purchase UOM %s not found' %values.get('uom_po_id') ))
            uom_po_id = uom_po_search_id.id


        if values.get('barcode') == '':
            barcode  = None
        else:
            barcode_val = values.get('barcode').split(".")
            barcode = barcode_val[0]
        if ((values.get('can_be_sold')) in ['0','0.0','False']):    
            can_be_sold = False
        else:
            can_be_sold = True
        if ((values.get('can_be_purchased')) in ['0','0.0','False']):    
            can_be_purchased = False
        else:
            can_be_purchased = True
        if ((values.get('is_published')) in ['0','0.0','False']):    
            is_published = False
        else:
            is_published = True
        e_categ = []
        if values.get('e_categ'):
            if ';' in values.get('e_categ'):
                e_names = values.get('e_categ').split(';')
                for name in e_names:
                    categ = self.env['product.public.category'].search([('name', '=', name)])
                    if not categ:
                        # Crear la categoría de e-commerce automáticamente
                        categ = self.env['product.public.category'].create({'name': name})
                        _logger.info('Created new e-commerce category: %s', name)
                    e_categ.append(categ.id)

            elif ',' in values.get('e_categ'):
                e_names = values.get('e_categ').split(',')
                for name in e_names:
                    categ = self.env['product.public.category'].search([('name', '=', name)])
                    if not categ:
                        # Crear la categoría de e-commerce automáticamente
                        categ = self.env['product.public.category'].create({'name': name})
                        _logger.info('Created new e-commerce category: %s', name)
                    e_categ.append(categ.id)

            else:
                e_names = values.get('e_categ').split(',')
                for name in e_names:
                    categ = self.env['product.public.category'].search([('name', '=', name)])
                    if not categ:
                        # Crear la categoría de e-commerce automáticamente
                        categ = self.env['product.public.category'].create({'name': name})
                        _logger.info('Created new e-commerce category: %s', name)
                    e_categ.append(categ.id)
        tax_id_lst = []
        if values.get('taxes_id'):
            if ';' in values.get('taxes_id'):
                tax_names = values.get('taxes_id').split(';')
                for name in tax_names:
                    tax = self.env['account.tax'].search([('name', '=', name), ('type_tax_use', '=', 'sale')])
                    if not tax:
                        raise ValidationError(_('"%s" Tax not in your system') % name)
                    tax_id_lst.append(tax.id)

            elif ',' in values.get('taxes_id'):
                tax_names = values.get('taxes_id').split(',')
                for name in tax_names:
                    tax = self.env['account.tax'].search([('name', '=', name), ('type_tax_use', '=', 'sale')])
                    if not tax:
                        raise ValidationError(_('"%s" Tax not in your system') % name)
                    tax_id_lst.append(tax.id)

            else:
                tax_names = values.get('taxes_id').split(',')
                tax = self.env['account.tax'].search([('name', 'in', tax_names), ('type_tax_use', '=', 'sale')])
                if not tax:
                    raise ValidationError(_('"%s" Tax not in your system') % tax_names)
                tax_id_lst.append(tax.id)
        supplier_taxes_id = []
        if values.get('supplier_taxes_id'):
            if ';' in values.get('supplier_taxes_id'):
                tax_names = values.get('supplier_taxes_id').split(';')
                for name in tax_names:
                    tax = self.env['account.tax'].search([('name', '=', name), ('type_tax_use', '=', 'purchase')])
                    if not tax:
                        raise ValidationError(_('"%s" Tax not in your system') % name)
                    supplier_taxes_id.append(tax.id)

            elif ',' in values.get('supplier_taxes_id'):
                tax_names = values.get('supplier_taxes_id').split(',')
                for name in tax_names:
                    tax = self.env['account.tax'].search([('name', '=', name), ('type_tax_use', '=', 'purchase')])
                    if not tax:
                        raise ValidationError(_('"%s" Tax not in your system') % name)
                    supplier_taxes_id.append(tax.id)

            else:
                tax_names = values.get('supplier_taxes_id').split(',')
                tax = self.env['account.tax'].search([('name', 'in', tax_names), ('type_tax_use', '=', 'purchase')])
                if not tax:
                    raise ValidationError(_('"%s" Tax not in your system') % tax_names)
                supplier_taxes_id.append(tax.id)

        image_medium = False
        if values.get('image'):
            try:
                u = urllib.request.urlopen(values.get('image'))
                if u:
                    image = u.read()
                image_base64 = base64.encodebytes(image)
                image_medium = image_base64 
            except:
                _logger.warning('Issue in Import Image : Url is not found')                                        
        else:
            image_medium = False

        if values.get('on_hand') == '':
            quantity = False
        else:
            quantity = values.get('on_hand')
        vals = {
                'name':values.get('name'),
                'uniq_id':values.get('u_id'),
                'default_code':values.get('default_code'),
                'barcode':barcode,
                'weight':values.get('weight'),
                'volume':values.get('volume'),
                'image_1920':image_medium,
                'description_sale':values.get('des_cust'),
                'categ_id':categ_id[0].id,
                'sale_ok':can_be_sold,
                'purchase_ok':can_be_purchased,
                'invoice_policy':values.get('invoice_policy'),
                'website_published':is_published,
                'public_categ_ids':[(6,0,e_categ)],
                'taxes_id':[(6,0,tax_id_lst)],
                'supplier_taxes_id':[(6,0,supplier_taxes_id)],
                'type':categ_type,
                'uom_id':uom_id,
                'uom_po_id':uom_po_id,
                'list_price':values.get('sale_price'),
                'standard_price':float(values.get('cost_price')) if values.get('cost_price') != '' else 0.0,

                }
        main_list = values.keys()
        count = 0
        custom_vals = {}
        for i in main_list:
            count+= 1
            model_id1 = self.env['ir.model'].search([('model','=','product.template')])    
            model_id2 = self.env['ir.model'].search([('model','=','product.product')])            

            if count > 25:
                if type(i) == bytes:
                    normal_details = i.decode('utf-8')
                else:
                    normal_details = i
                if normal_details.startswith('x_'):
                    any_special = self.check_splcharacter(normal_details)
                    if any_special:
                        split_fields_name = normal_details.split("@")
                        technical_fields_name = split_fields_name[0]
                        many2x_fields1 = self.env['ir.model.fields'].search([('name','=',technical_fields_name),('state','=','manual'),('model_id','=',model_id1.id)])
                        many2x_fields2 = self.env['ir.model.fields'].search([('name','=',technical_fields_name),('state','=','manual'),('model_id','=',model_id2.id)])
                        if many2x_fields1.id:
                            if many2x_fields1.ttype in ['many2one','many2many']: 
                                if many2x_fields1.ttype =="many2one":
                                    if values.get(i):
                                        fetch_m2o = self.env[many2x_fields1.relation].search([('name','=',values.get(i))])
                                        if fetch_m2o.id:
                                            custom_vals.update({
                                                technical_fields_name: fetch_m2o.id
                                                })
                                        else:
                                            raise ValidationError(_('"%s" This custom field value "%s" not available in system') % (i , values.get(i)))
                                if many2x_fields1.ttype =="many2many":
                                    m2m_value_lst = []
                                    if values.get(i):
                                        if ';' in values.get(i):
                                            m2m_names = values.get(i).split(';')
                                            for name in m2m_names:
                                                m2m_id = self.env[many2x_fields1.relation].search([('name', '=', name)])
                                                if not m2m_id:
                                                    raise ValidationError(_('"%s" This custom field value "%s" not available in system') % (i , name))
                                                m2m_value_lst.append(m2m_id.id)

                                        elif ',' in values.get(i):
                                            m2m_names = values.get(i).split(',')
                                            for name in m2m_names:
                                                m2m_id = self.env[many2x_fields1.relation].search([('name', '=', name)])
                                                if not m2m_id:
                                                    raise ValidationError(_('"%s" This custom field value "%s" not available in system') % (i , name))
                                                m2m_value_lst.append(m2m_id.id)

                                        else:
                                            m2m_names = values.get(i).split(',')
                                            m2m_id = self.env[many2x_fields1.relation].search([('name', 'in', m2m_names)])
                                            if not m2m_id:
                                                raise ValidationError(_('"%s" This custom field value "%s" not available in system') % (i , m2m_names))
                                            m2m_value_lst.append(m2m_id.id)
                                    custom_vals.update({
                                        technical_fields_name : m2m_value_lst
                                        })        
                            else:
                                raise ValidationError(_('"%s" This custom field type is not many2one/many2many') % technical_fields_name)                                                                                                                                
                        if many2x_fields2.id:
                            if many2x_fields2.ttype in ['many2one','many2many']: 

                                if many2x_fields2.ttype =="many2one":
                                    if values.get(i):
                                        fetch_m2o = self.env[many2x_fields2.relation].search([('name','=',values.get(i))])
                                        if fetch_m2o.id:
                                            custom_vals.update({
                                                technical_fields_name: fetch_m2o.id
                                                })
                                        else:
                                            raise ValidationError(_('"%s" This custom field value "%s" not available in system') % (i , values.get(i)))
                                if many2x_fields2.ttype =="many2many":
                                    m2m_value_lst = []
                                    if values.get(i):
                                        if ';' in values.get(i):
                                            m2m_names = values.get(i).split(';')
                                            for name in m2m_names:
                                                m2m_id = self.env[many2x_fields2.relation].search([('name', '=', name)])
                                                if not m2m_id:
                                                    raise ValidationError(_('"%s" This custom field value "%s" not available in system') % (i , name))
                                                m2m_value_lst.append(m2m_id.id)

                                        elif ',' in values.get(i):
                                            m2m_names = values.get(i).split(',')
                                            for name in m2m_names:
                                                m2m_id = self.env[many2x_fields2.relation].search([('name', '=', name)])
                                                if not m2m_id:
                                                    raise ValidationError(_('"%s" This custom field value "%s" not available in system') % (i , name))
                                                m2m_value_lst.append(m2m_id.id)

                                        else:
                                            m2m_names = values.get(i).split(',')
                                            m2m_id = self.env[many2x_fields2.relation].search([('name', 'in', m2m_names)])
                                            if not m2m_id:
                                                raise ValidationError(_('"%s" This custom field value "%s" not available in system') % (i , m2m_names))
                                            m2m_value_lst.append(m2m_id.id)
                                    custom_vals.update({
                                        technical_fields_name : m2m_value_lst
                                        })        
                            else:
                                raise ValidationError(_('"%s" This custom field type is not many2one/many2many') % technical_fields_name)                                                                                                                                
                        else:
                            raise ValidationError(_('"%s" This m2x custom field is not available in system') % technical_fields_name)
                    else:
                        normal_fields1 = self.env['ir.model.fields'].search([('name','=',normal_details),('state','=','manual'),('model_id','=',model_id1.id)])
                        normal_fields2 = self.env['ir.model.fields'].search([('name','=',normal_details),('state','=','manual'),('model_id','=',model_id2.id)])

                        if normal_fields1.id:
                            if normal_fields1.ttype ==  'boolean':
                                custom_vals.update({
                                    normal_details : values.get(i)
                                    })
                            elif normal_fields1.ttype == 'char':
                                custom_vals.update({
                                    normal_details : values.get(i)
                                    })                                
                            elif normal_fields1.ttype == 'float':
                                if values.get(i) == '':
                                    float_value = 0.0
                                else:
                                    float_value = float(values.get(i)) 
                                custom_vals.update({
                                    normal_details : float_value
                                    })                              
                            elif normal_fields1.ttype == 'integer':
                                if values.get(i) == '':
                                    int_value = 0
                                else:
                                    int_value = int(values.get(i)) 
                                custom_vals.update({
                                    normal_details : int_value
                                    })                                   
                            elif normal_fields1.ttype == 'selection':
                                custom_vals.update({
                                    normal_details : values.get(i)
                                    })                                
                            elif normal_fields1.ttype == 'text':
                                custom_vals.update({
                                    normal_details : values.get(i)
                                    })
                        elif normal_fields2.id:
                            if normal_fields2.ttype ==  'boolean':
                                custom_vals.update({
                                    normal_details : values.get(i)
                                    })
                            elif normal_fields2.ttype == 'char':
                                custom_vals.update({
                                    normal_details : values.get(i)
                                    })                                
                            elif normal_fields2.ttype == 'float':
                                if values.get(i) == '':
                                    float_value = 0.0
                                else:
                                    float_value = float(values.get(i)) 
                                custom_vals.update({
                                    normal_details : float_value
                                    })                              
                            elif normal_fields2.ttype == 'integer':
                                if values.get(i) == '':
                                    int_value = 0
                                else:
                                    int_value = int(values.get(i)) 
                                custom_vals.update({
                                    normal_details : int_value
                                    })                                   
                            elif normal_fields2.ttype == 'selection':
                                custom_vals.update({
                                    normal_details : values.get(i)
                                    })                                
                            elif normal_fields2.ttype == 'text':
                                custom_vals.update({
                                    normal_details : values.get(i)
                                    })                                    
                        else:
                            raise ValidationError(_('"%s" This custom field is not available in system') % normal_details)        
        
        
        if self.product_option == 'update':
            if self.product_search == 'by_name':
                product_temp = product_tmpl_obj.search([('name','=',values.get('name')),('uniq_id','=',values.get('u_id'))],limit=1)
            elif self.product_search == 'by_barcode':
                product_temp = product_tmpl_obj.search([('barcode','=',values.get('barcode')),('uniq_id','=',values.get('u_id'))],limit=1)
            elif self.product_search == 'by_code':            
                product_temp = product_tmpl_obj.search([('default_code','=',values.get('default_code')),('uniq_id','=',values.get('u_id'))],limit=1)
        else:
            product_temp = product_tmpl_obj.search([('name','=',values.get('name')),('uniq_id','=',values.get('u_id'))],limit=1)

        res = False
        if not product_temp:
            product_temp = product_tmpl_obj.create(vals)
            res = product_temp.product_variant_id

        template = False
        if product_temp and values.get('attributes'):
            template = product_temp
            ids = []
            tmpl_attribute_value = []
            atr = values.get('attributes').split(',')
            counter = 0
            for pair in atr:
                attribute = self.env['product.attribute'].search([['name','=',pair]],limit=1)
                if not attribute:
                    if pair in ('color','colour','Color','Colour'):
                        attribute = self.env['product.attribute'].create({'name': 'Color','type':'color'})
                    else:
                        attribute = self.env['product.attribute'].create({'name': pair})  
                
                atr_value = values.get('attribute_value').split(',')
                temp = atr_value[counter].split('@')
                attr = temp[0]
                attr_values = temp[1].split(';')
                counter +=1        
                attribute_value = self.env['product.attribute.value'].search([('name','=',temp[0]), ('attribute_id', '=', attribute.id)], limit=1)
                if not attribute_value:
                    if attr in ('color','colour','Color','Colour'):
                        attribute_value = self.env['product.attribute.value'].create({
                            'name':temp[0],
                            'attribute_id':attribute.id,
                            'html_color':temp[0].lower(), 
                        })
                    else:
                        attribute_value = self.env['product.attribute.value'].create({
                            'name':temp[0],
                            'attribute_id':attribute.id ,
                            })
                
                if not attribute_value or not attribute_value.id:
                    raise ValidationError(_('Could not create or find attribute value for "%s"') % temp[0])
                
                tmpl_attribute_value.append(attribute_value.id)
                attribute_line = self.env['product.template.attribute.line'].search([
                    ('attribute_id','=',attribute.id),('product_tmpl_id','=',template.id)
                    ],limit=1)
                if attribute_line :
                    vv = attribute_line.value_ids.ids
                    if attribute_value.id not in vv :
                        vv.append(attribute_value.id)
                    attribute_line.write({
                        'value_ids' : [(6,0,vv)],
                    })
                else:
                    attribute_line = self.env['product.template.attribute.line'].create({
                            'attribute_id':attribute.id,
                            'product_tmpl_id': template.id,
                            'value_ids':[(6,0,[attribute_value.id])],
                            'active':True,
                        })                
                ptav = self.env['product.template.attribute.value'].search([
                    ('product_tmpl_id', '=', template.id),
                    ('attribute_id','=',attribute.id),
                    ('name','=',attribute_value.name)])
                if not ptav:
                    ptav = self.env['product.template.attribute.value'].create({
                        'product_attribute_value_id': attribute_value.id,
                        'attribute_line_id': attribute_line.id
                        })
                ids.extend(ptav.ids)
            if ids:
                new_product_ids = self.env['product.product'].search([
                    ('product_tmpl_id','=',template.id)])
                
                prd_id = new_product_ids.filtered(lambda x : x.product_template_attribute_value_ids.ids == ids)
                
                if prd_id :
                    res = prd_id
                    vals.update({
                        'imported_prod':True,
                    })
                    prd_id.write(vals)
                else:
                    vals.update({
                        'imported_prod':True,
                        'product_tmpl_id':template.id,
                        'product_template_attribute_value_ids':[(6,0,ids)],
                    })
                    res = product_obj.create(vals)
            template.write({
                'list_price' : values.get('sale_price'),
                'standard_price':float(values.get('cost_price')) if values.get('cost_price') != '' else 0.0,
            })

        if self.product_option == 'update':
            if self.product_search == 'by_name':
                product_temp_id = product_tmpl_obj.search([('name','=',values.get('name')),('uniq_id','=',values.get('u_id'))],limit=1)
            elif self.product_search == 'by_barcode':
                product_temp_id = product_tmpl_obj.search([('barcode','=',values.get('barcode')),('uniq_id','=',values.get('u_id'))],limit=1)
            elif self.product_search == 'by_code':            
                product_temp_id = product_tmpl_obj.search([('default_code','=',values.get('default_code')),('uniq_id','=',values.get('u_id'))],limit=1)
        else:            
            product_temp_id = product_tmpl_obj.search([('name','=',values.get('name')),('uniq_id','=',values.get('u_id'))],limit=1)
        if product_temp_id :
            if values.get('attributes'):
                atr = values.get('attributes').split(',')
                counter = 0
                for pair in atr:
                    attribute = self.env['product.attribute'].search([['name','=',pair]],limit=1)
                    if not attribute:
                        if pair in ('color','colour','Color','Colour'):
                            attribute = self.env['product.attribute'].create({'name': 'Color','type':'color'})
                        else:
                            attribute = self.env['product.attribute'].create({'name': pair})  
                    atr_value = values.get('attribute_value').split(',')
                    temp = atr_value[counter].split('@')
                    attr = temp[0]
                    attr_values = temp[1].split(';')
                    counter +=1        
                    value_rec = self.env['product.attribute.value'].search([('name','=',temp[0]), ('attribute_id', '=', attribute.id)], limit=1)
                    if value_rec:
                        product_template_attribute_values = self.env['product.template.attribute.value'].search([('product_tmpl_id', '=', product_temp_id.id),('attribute_id','=',attribute.id),('name','=',value_rec.name)])
                        if product_template_attribute_values:
                            product_template_attribute_values.price_extra = temp[1]
            product_temp_id.write({
                'list_price' : values.get('sale_price'),
                'standard_price':float(values.get('cost_price')) if values.get('cost_price') != '' else 0.0,
            })
        if res:
            res.write(custom_vals)
        if values.get('extra_img'):
            if ';' in values.get('extra_img'):
                img_names = values.get('extra_img').split(';')
                for name in img_names:
                    try:
                        u = urllib.request.urlopen(name)
                        if u:
                            image = u.read()
                            image_base64 = base64.encodebytes(image)
                            image_medium = image_base64 
                            imgs = self.create_img(image_medium, template)
                    except:
                        _logger.warning('Issue in Import Image : Url is not found')        
            else:
                try:
                    u = urllib.request.urlopen(values.get('extra_img'))
                    if u:
                        image = u.read()
                        image_base64 = base64.encodebytes(image)
                        image_medium = image_base64 
                        imgs = self.create_img(image_medium, template)
                except:
                    _logger.warning('Issue in Import Image : Url is not found')        

        if values.get('extra_var_img'):
            if ';' in values.get('extra_var_img'):
                img_names = values.get('extra_var_img').split(';')
                for name in img_names:
                    try:
                        u = urllib.request.urlopen(name)
                        if u:
                            image = u.read()
                            image_base64 = base64.encodebytes(image)
                            image_medium = image_base64 
                            imgs = self.create_var_img(image_medium, res)
                    except:
                        _logger.warning('Issue in Import Image : Url is not found')        
            else:
                try:
                    u = urllib.request.urlopen(values.get('extra_img'))
                    if u:
                        image = u.read()
                        image_base64 = base64.encodebytes(image)
                        image_medium = image_base64 
                        imgs = self.create_img(image_medium, template)
                except:
                    _logger.warning('Issue in Import Image : Url is not found')        
        if res:        
            res.write({'sale_ok':can_be_sold,
                    'purchase_ok':can_be_purchased,})

        if template:        
            prd_ids = template.product_variant_ids.filtered(lambda x : x.imported_prod == False)
            if prd_ids:
                prd_ids.unlink()

        if res:
            if res.type=='product':
                company_user = self.env.user.company_id
                location = self.env['stock.warehouse'].search([('company_id', '=', company_user.id)], limit=1).in_type_id.default_location_dest_id
                product = res.with_context(location=location.id)
                th_qty = res.qty_available



                Inventory = self.env['stock.quant']
                if quantity:
                    inventory = Inventory.create({
                        'product_id':res.id,
                        'inventory_quantity':quantity,
                        'location_id':location.id
                        })

                    inventory.action_apply_inventory()

    def import_variants(self):
        if self.import_option == 'csv':
            keys = ['u_id', 'name', 'default_code', 'categ_id', 'type', 'barcode',
                    'uom_id', 'uom_po_id', 'sale_price', 'cost_price', 'weight', 'volume',
                    'taxes_id', 'supplier_taxes_id', 'can_be_sold', 'can_be_purchased', 'invoice_policy',
                    'is_published', 'attributes', 'attribute_value', 'on_hand', 'e_categ', 'des_cust', 'image',
                    'extra_img', 'extra_var_img']
            try:
                csv_data = base64.b64decode(self.file)
                data_file = io.StringIO(csv_data.decode("utf-8"))
                data_file.seek(0)
                file_reader = []
                csv_reader = csv.reader(data_file, delimiter=',')
                file_reader.extend(csv_reader)
            except Exception:
                raise ValidationError(_("Please select CSV/XLS file or You have selected invalid file"))
            
            total_records = len(file_reader) - 1  # Excluir la fila de encabezados
            _logger.info('Starting CSV import with %s records to process', total_records)
            
            values = {}
            for i in range(len(file_reader)):
                field = list(map(str, file_reader[i]))
                count = 1
                count_keys = len(keys)
                if len(field) > count_keys:
                    for new_fields in field:
                        if count > count_keys:
                            keys.append(new_fields)
                        count += 1
                values = dict(zip(keys, field))
                if values:
                    if i == 0:
                        continue
                    else:
                        # Log de progreso cada 10 registros o en el último
                        if i % 10 == 0 or i == len(file_reader) - 1:
                            _logger.info('Processing CSV record %s/%s: %s', i, total_records, values.get('name', 'Unknown'))
                        
                        if self.product_option == 'create':
                            res = self.create_product(values)
                        elif self.product_option == 'update':
                            if values.get('barcode') == '':
                                barcode = None
                            else:
                                barcode = values.get('barcode')
                                barcode = barcode.split(".")

                            if self.product_search == 'by_barcode':
                                if not barcode:
                                    raise ValidationError(_('Please give Barcode for updating Products'))
                                product_ids = self.env['product.product'].search([('barcode', '=', barcode[0])],
                                                                                 limit=1)

                            if self.product_search == 'by_name':
                                if not values.get('name'):
                                    raise ValidationError(_('Please give Name for updating Products'))
                                if not barcode:
                                    raise ValidationError(_('Please give Barcode for updating Products'))

                                product_ids = self.env['product.product'].search(
                                    [('name', '=', values.get('name')), ('barcode', '=', barcode[0])], limit=1)

                            if self.product_search == 'by_code':
                                if not values.get('default_code'):
                                    raise ValidationError(_('Please give Internal Reference for updating Products'))
                                product_ids = self.env['product.product'].search(
                                    [('default_code', '=', values.get('default_code'))], limit=1)

                            if product_ids:

                                product_tmpl_obj = self.env['product.template']
                                product_obj = self.env['product.product']
                                product_categ_obj = self.env['product.category']
                                product_uom_obj = self.env['uom.uom']
                                categ_id = False
                                categ_type = False
                                barcode = False
                                uom_id = False
                                uom_po_id = False
                                fix_price = False
                                if values.get('barcode') == '':
                                    pass
                                else:
                                    barcode = values.get('barcode')
                                    barcode = barcode.split(".")

                                if values.get('categ_id') == '':
                                    pass
                                else:
                                    categ_id = product_categ_obj.search([('name', '=', values.get('categ_id'))],
                                                                        limit=1)
                                    if not categ_id:
                                        # Crear la categoría automáticamente si no existe
                                        categ_id = product_categ_obj.create({'name': values.get('categ_id')})
                                        _logger.info('Created new category: %s', values.get('categ_id'))
                                if values.get('type') == '':
                                    pass
                                else:
                                    if values.get('type') == 'Consumable':
                                        categ_type = 'consu'
                                    elif values.get('type') == 'Service':
                                        categ_type = 'service'
                                    elif values.get('type') == 'Stockable Product':
                                        categ_type = 'product'
                                    else:
                                        categ_type = 'product'

                                if values.get('uom_id') == '':
                                    pass
                                else:
                                    uom_search_id = product_uom_obj.search([('name', '=', values.get('uom_id'))])
                                    if not uom_search_id:
                                        raise ValidationError(_('UOM %s not found.' % values.get('uom_id')))
                                    else:
                                        uom_id = uom_search_id.id

                                if values.get('uom_po_id') == '':
                                    pass
                                else:
                                    uom_po_search_id = product_uom_obj.search([('name', '=', values.get('uom_po_id'))])
                                    if not uom_po_search_id:
                                        raise ValidationError(_('Purchase UOM %s not found' % values.get('uom_po_id')))
                                    else:
                                        uom_po_id = uom_po_search_id.id
                                e_categ = []
                                if values.get('e_categ'):
                                    if ';' in values.get('e_categ'):
                                        e_names = values.get('e_categ').split(';')
                                        for name in e_names:
                                            categ = self.env['product.public.category'].search([('name', '=', name)])
                                            if not categ:
                                                # Crear la categoría de e-commerce automáticamente
                                                categ = self.env['product.public.category'].create({'name': name})
                                                _logger.info('Created new e-commerce category: %s', name)
                                            e_categ.append(categ.id)

                                    elif ',' in values.get('e_categ'):
                                        e_names = values.get('e_categ').split(',')
                                        for name in e_names:
                                            categ = self.env['product.public.category'].search([('name', '=', name)])
                                            if not categ:
                                                # Crear la categoría de e-commerce automáticamente
                                                categ = self.env['product.public.category'].create({'name': name})
                                                _logger.info('Created new e-commerce category: %s', name)
                                            e_categ.append(categ.id)

                                    else:
                                        e_names = values.get('e_categ').split(',')
                                        for name in e_names:
                                            categ = self.env['product.public.category'].search([('name', '=', name)])
                                            if not categ:
                                                # Crear la categoría de e-commerce automáticamente
                                                categ = self.env['product.public.category'].create({'name': name})
                                                _logger.info('Created new e-commerce category: %s', name)
                                            e_categ.append(categ.id)

                                tax_id_lst = []
                                if values.get('taxes_id'):
                                    if ';' in values.get('taxes_id'):
                                        tax_names = values.get('taxes_id').split(';')
                                        for name in tax_names:
                                            tax = self.env['account.tax'].search([('name', '=', name), ('type_tax_use', '=', 'sale')])
                                            if not tax:
                                                raise ValidationError(_('"%s" Tax not in your system') % name)
                                            tax_id_lst.append(tax.id)

                                    elif ',' in values.get('taxes_id'):
                                        tax_names = values.get('taxes_id').split(',')
                                        for name in tax_names:
                                            tax = self.env['account.tax'].search([('name', '=', name), ('type_tax_use', '=', 'sale')])
                                            if not tax:
                                                raise ValidationError(_('"%s" Tax not in your system') % name)
                                            tax_id_lst.append(tax.id)

                                    else:
                                        tax_names = values.get('taxes_id').split(',')
                                        tax = self.env['account.tax'].search([('name', 'in', tax_names), ('type_tax_use', '=', 'sale')])
                                        if not tax:
                                            raise ValidationError(_('"%s" Tax not in your system') % tax_names)
                                        tax_id_lst.append(tax.id)

                                supplier_taxes_id = []
                                if values.get('supplier_taxes_id'):
                                    if ';' in values.get('supplier_taxes_id'):
                                        tax_names = values.get('supplier_taxes_id').split(';')
                                        for name in tax_names:
                                            tax = self.env['account.tax'].search([('name', '=', name), ('type_tax_use', '=', 'purchase')])
                                            if not tax:
                                                raise ValidationError(_('"%s" Tax not in your system') % name)
                                            supplier_taxes_id.append(tax.id)

                                elif ',' in values.get('supplier_taxes_id'):
                                    tax_names = values.get('supplier_taxes_id').split(',')
                                    for name in tax_names:
                                        tax = self.env['account.tax'].search([('name', '=', name), ('type_tax_use', '=', 'purchase')])
                                        if not tax:
                                            raise ValidationError(_('"%s" Tax not in your system') % name)
                                        supplier_taxes_id.append(tax.id)

                                else:
                                    tax_names = values.get('supplier_taxes_id').split(',')
                                    tax = self.env['account.tax'].search([('name', 'in', tax_names), ('type_tax_use', '=', 'purchase')])
                                    if not tax:
                                        raise ValidationError(_('"%s" Tax not in your system') % tax_names)
                                    supplier_taxes_id.append(tax.id)

                                if values.get('on_hand') == '':
                                    quantity = False
                                else:
                                    quantity = values.get('on_hand')

                                if ((values.get('can_be_sold')) in ['0', '0.0', 'False']):
                                    can_be_sold = False
                                else:
                                    can_be_sold = True
                                if ((values.get('can_be_purchased')) in ['0', '0.0', 'False']):
                                    can_be_purchased = False
                                else:
                                    can_be_purchased = True
                                if ((values.get('is_published')) in ['0', '0.0', 'False']):
                                    is_published = False
                                else:
                                    is_published = True

                                if values.get('can_be_sold'):
                                    product_ids.write({'sale_ok': can_be_sold or False})
                                if values.get('can_be_purchased'):
                                    product_ids.write({'purchase_ok': can_be_purchased or False})
                                if values.get('is_published'):
                                    product_ids.write({'website_published': is_published or False})

                                if categ_id != False:
                                    product_ids.write({'categ_id': categ_id[0].id or False})
                                if categ_type != False:
                                    product_ids.write({'type': categ_type or False})
                                if self.product_search == 'by_name':
                                    if values.get('default_code'):
                                        product_ids.write({'default_code': values.get('default_code') or False})
                                    if barcode != False:
                                        product_ids.write({'barcode': barcode[0] or False})
                                if self.product_search == 'by_code':
                                    if values.get('name'):
                                        product_ids.write({'name': values.get('name') or False})
                                    if barcode != False:
                                        product_ids.write({'barcode': barcode[0] or False})
                                if self.product_search == 'by_barcode':
                                    if values.get('default_code'):
                                        product_ids.write({'default_code': values.get('default_code') or False})
                                    if values.get('name'):
                                        product_ids.write({'name': values.get('name') or False})
                                if uom_id != False:
                                    product_ids.write({'uom_id': uom_id or False})
                                if uom_po_id != False:
                                    product_ids.write({'uom_po_id': uom_po_id})
                                if values.get('sale_price'):
                                    product_ids.write({'lst_price': float(values.get('sale_price')) or False})
                                if values.get('cost_price'):
                                    product_ids.write({'standard_price': float(values.get('cost_price')) or False})
                                if values.get('weight'):
                                    product_ids.write({'weight': values.get('weight') or False})
                                if values.get('volume'):
                                    product_ids.write({'volume': values.get('volume') or False})
                                if values.get('des_cust'):
                                    product_ids.write({'description_sale': values.get('des_cust') or False})
                                if values.get('invoice_policy'):
                                    product_ids.write({'invoice_policy': values.get('invoice_policy') or False})

                                if values.get('image'):
                                    try:
                                        u = urllib.request.urlopen(values.get('image'))
                                        if u:
                                            image = u.read()
                                            image_base64 = base64.encodebytes(image)
                                            image_medium = image_base64
                                            imgs = self.create_img(image_medium, template)
                                    except:
                                        _logger.warning('Issue in Import Image : Url is not found')

                                product_ids.write({
                                    'taxes_id': [(4, tax_id) for tax_id in tax_id_lst],
                                    'supplier_taxes_id': [(4, tax_id) for tax_id in supplier_taxes_id],
                                    'public_categ_ids': [(6, 0, e_categ)]
                                })

                                for product in product_ids:
                                    if product.type == 'product':
                                        company_user = self.env.user.company_id
                                        location = self.env['stock.warehouse'].search(
                                            [('company_id', '=', company_user.id)],
                                            limit=1).in_type_id.default_location_dest_id
                                        product = product.with_context(location=location.id)
                                        th_qty = product.qty_available

                                        Inventory = self.env['stock.quant']
                                        if quantity:
                                            inventory = Inventory.create({
                                                'product_id': product.id,
                                                'inventory_quantity': quantity,
                                                'location_id': location.id
                                            })

                                            inventory.action_apply_inventory()
                            else:
                                self.create_product(values)

            context = {'default_name': "%s Records Successfully Imported." % (i)
                       }
            _logger.info('CSV import completed successfully. Total records processed: %s', total_records)
            return {
                'name': 'Success',
                'type': 'ir.actions.act_window',
                'view_type': 'form',
                'view_mode': 'form',
                'res_model': 'custom.pop.message',
                'target': 'new',
                'context': context
            }
            return res


        elif self.import_option == 'xls':
            list_record = []
            d = {}
            try:
                fp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
                fp.write(binascii.a2b_base64(self.file))
                fp.seek(0)
                values = {}
                sale_ids = []
                workbook = xlrd.open_workbook(fp.name)
                sheet = workbook.sheet_by_index(0)
            except Exception:
                raise ValidationError(_("Invalid file!"))
            
            total_records = sheet.nrows - 1  # Excluir la fila de encabezados
            _logger.info('Starting XLS import with %s records to process', total_records)
            
            for row_no in range(sheet.nrows):
                val = {}
                if row_no <= 0:
                    line_fields = list(map(lambda row: row.value.encode('utf-8'), sheet.row(row_no)))
                else:
                    # Log de progreso cada 10 registros o en el último
                    if row_no % 10 == 0 or row_no == sheet.nrows - 1:
                        _logger.info('Processing XLS record %s/%s', row_no, total_records)
                    
                    line = list(
                        map(lambda row: isinstance(row.value, bytes) and row.value.encode('utf-8') or str(row.value),
                            sheet.row(row_no)))

                    values.update({
                        'u_id': line[0],
                        'name': line[1],
                        'default_code': line[2],
                        'categ_id': line[3],
                        'type': line[4],
                        'barcode': line[5],
                        'uom_id': line[6],
                        'uom_po_id': line[7],
                        'sale_price': line[8],
                        'cost_price': line[9],
                        'weight': line[10],
                        'volume': line[11],
                        'taxes_id': line[12],
                        'supplier_taxes_id': line[13],
                        'can_be_sold': line[14],
                        'can_be_purchased': line[15],
                        'invoice_policy': line[16],
                        'is_published': line[17],
                        'attributes': line[18],
                        'attribute_value': line[19],
                        'on_hand': line[20],
                        'e_categ': line[21],
                        'des_cust': line[22],
                        'image': line[23],
                        'extra_img': line[24],
                        'extra_var_img': line[25]

                    })
                    count = 0
                    for l_fields in line_fields:
                        if count > 25:
                            values.update({l_fields: line[count]})
                        count += 1
                    if self.product_option == 'create':

                        res = self.create_product(values)

                    elif self.product_option == 'update':

                        if line[5] == '':
                            barcode = None
                        else:
                            barcode = line[5]
                            barcode = barcode.split(".")

                        if self.product_search == 'by_barcode':
                            if not barcode:
                                raise ValidationError(_('Please give Barcode for updating Products'))
                            product_ids = self.env['product.product'].search([('barcode', '=', barcode[0])], limit=1)
                        if self.product_search == 'by_name':
                            if not line[1]:
                                raise ValidationError(_('Please give Name for updating Products'))
                            if not barcode:
                                raise ValidationError(_('Please give Barcode for updating Products'))

                            product_ids = self.env['product.product'].search(
                                [('name', '=', line[1]), ('barcode', '=', barcode[0])], limit=1)

                        if self.product_search == 'by_code':
                            if not line[2]:
                                raise ValidationError(_('Please give Internal Reference for updating Products'))
                            product_ids = self.env['product.product'].search([('default_code', '=', line[2])], limit=1)

                        if product_ids:
                            product_tmpl_obj = self.env['product.template']
                            product_obj = self.env['product.product']
                            product_categ_obj = self.env['product.category']
                            product_uom_obj = self.env['uom.uom']
                            categ_id = False
                            categ_type = False
                            barcode = False
                            uom_id = False
                            uom_po_id = False
                            fix_price = False

                            if line[5] == '':
                                pass
                            else:
                                barcode = line[5]
                                barcode = barcode.split(".")

                            if line[3] == '':
                                pass
                            else:
                                categ_id = product_categ_obj.search([('name', '=', line[3])], limit=1)
                                if not categ_id:
                                    # Crear la categoría automáticamente si no existe
                                    categ_id = product_categ_obj.create({'name': line[3]})
                                    _logger.info('Created new category: %s', line[3])
                            if line[4] == '':
                                pass
                            else:
                                if line[4] == 'Consumable':
                                    categ_type = 'consu'
                                elif line[4] == 'Service':
                                    categ_type = 'service'
                                elif line[4] == 'Stockable Product':
                                    categ_type = 'product'
                                else:
                                    categ_type = 'product'

                            if line[6] == '':
                                pass
                            else:
                                uom_search_id = product_uom_obj.search([('name', '=', line[6])])
                                if not uom_search_id:
                                    raise ValidationError(_('UOM %s not found.' % line[6]))
                                else:
                                    uom_id = uom_search_id.id

                            if line[7] == '':
                                pass
                            else:
                                uom_po_search_id = product_uom_obj.search([('name', '=', line[7])])
                                if not uom_po_search_id:
                                    raise ValidationError(_('Purchase UOM %s not found' % line[7]))
                                else:
                                    uom_po_id = uom_po_search_id.id
                            e_categ = []
                            if line[21]:
                                if ';' in line[21]:
                                    e_names = line[21].split(';')
                                    for name in e_names:
                                        categ = self.env['product.public.category'].search([('name', '=', name)])
                                        if not categ:
                                            # Crear la categoría de e-commerce automáticamente
                                            categ = self.env['product.public.category'].create({'name': name})
                                            _logger.info('Created new e-commerce category: %s', name)
                                        e_categ.append(categ.id)

                                elif ',' in line[21]:
                                    e_names = line[21].split(',')
                                    for name in e_names:
                                        categ = self.env['product.public.category'].search([('name', '=', name)])
                                        if not categ:
                                            # Crear la categoría de e-commerce automáticamente
                                            categ = self.env['product.public.category'].create({'name': name})
                                            _logger.info('Created new e-commerce category: %s', name)
                                        e_categ.append(categ.id)

                                else:
                                    e_names = line[21].split(',')
                                    for name in e_names:
                                        categ = self.env['product.public.category'].search([('name', '=', name)])
                                        if not categ:
                                            # Crear la categoría de e-commerce automáticamente
                                            categ = self.env['product.public.category'].create({'name': name})
                                            _logger.info('Created new e-commerce category: %s', name)
                                        e_categ.append(categ.id)
                            tax_id_lst = []
                            if line[12]:
                                if ';' in line[12]:
                                    tax_names = line[12].split(';')
                                    for name in tax_names:
                                        tax = self.env['account.tax'].search(
                                            [('name', 'in', name), ('type_tax_use', '=', 'sale')])
                                        if not tax:
                                            raise ValidationError(_('"%s" Tax not in your system') % name)
                                        tax_id_lst.append(tax.id)

                                elif ',' in line[12]:
                                    tax_names = line[12].split(',')
                                    for name in tax_names:
                                        tax = self.env['account.tax'].search(
                                            [('name', 'in', name), ('type_tax_use', '=', 'sale')])
                                        if not tax:
                                            raise ValidationError(_('"%s" Tax not in your system') % name)
                                        tax_id_lst.append(tax.id)

                                else:
                                    tax_names = line[12].split(',')
                                    tax = self.env['account.tax'].search(
                                        [('name', 'in', tax_names), ('type_tax_use', '=', 'sale')])
                                    if not tax:
                                        raise ValidationError(_('"%s" Tax not in your system') % tax_names)
                                    tax_id_lst.append(tax.id)

                            supplier_taxes_id = []
                            if line[13]:
                                if ';' in line[13]:
                                    tax_names = line[13].split(';')
                                    for name in tax_names:
                                        tax = self.env['account.tax'].search(
                                            [('name', '=', name), ('type_tax_use', '=', 'purchase')])
                                        if not tax:
                                            raise ValidationError(_('"%s" Tax not in your system') % name)
                                        supplier_taxes_id.append(tax.id)

                                elif ',' in line[13]:
                                    tax_names = line[13].split(',')
                                    for name in tax_names:
                                        tax = self.env['account.tax'].search(
                                            [('name', '=', name), ('type_tax_use', '=', 'purchase')])
                                        if not tax:
                                            raise ValidationError(_('"%s" Tax not in your system') % name)
                                        supplier_taxes_id.append(tax.id)

                                else:
                                    tax_names = line[13].split(',')
                                    tax = self.env['account.tax'].search(
                                        [('name', '=', tax_names), ('type_tax_use', '=', 'purchase')])
                                    if not tax:
                                        raise ValidationError(_('"%s" Tax not in your system') % tax_names)
                                    supplier_taxes_id.append(tax.id)

                            if line[20] == '':
                                quantity = False
                            else:
                                quantity = line[20]

                            if ((line[14]) in ['0', '0.0', 'False']):
                                can_be_sold = False
                            else:
                                can_be_sold = True
                            if ((line[15]) in ['0', '0.0', 'False']):
                                can_be_purchased = False
                            else:
                                can_be_purchased = True
                            if ((line[17]) in ['0', '0.0', 'False']):
                                is_published = False
                            else:
                                is_published = True

                            if line[14]:
                                product_ids.write({'sale_ok': can_be_sold or False})
                            if line[15]:
                                product_ids.write({'purchase_ok': can_be_purchased or False})
                            if line[17]:
                                product_ids.write({'website_published': is_published or False})

                            if categ_id != False:
                                product_ids.write({'categ_id': categ_id[0].id or False})
                            if categ_type != False:
                                product_ids.write({'type': categ_type or False})
                            if self.product_search == 'by_name':
                                if line[2]:
                                    product_ids.write({'default_code': line[2] or False})
                                if barcode != False:
                                    product_ids.write({'barcode': barcode[0] or False})
                            if self.product_search == 'by_code':
                                if line[1]:
                                    product_ids.write({'name': line[1] or False})
                                if barcode != False:
                                    product_ids.write({'barcode': barcode[0] or False})
                            if self.product_search == 'by_barcode':
                                if line[2]:
                                    product_ids.write({'default_code': line[2] or False})
                                if line[1]:
                                    product_ids.write({'name': line[1] or False})

                            if uom_id != False:
                                product_ids.write({'uom_id': uom_id or False})
                            if uom_po_id != False:
                                product_ids.write({'uom_po_id': uom_po_id})
                            if line[8]:
                                product_ids.write({'lst_price': float(line[8]) or False})
                            if line[9]:
                                product_ids.write({'standard_price': float(line[9]) or False})
                            if line[10]:
                                product_ids.write({'weight': line[10] or False})
                            if line[11]:
                                product_ids.write({'volume': line[11] or False})
                            if line[22]:
                                product_ids.write({'description_sale': line[22] or False})
                            if line[16]:
                                product_ids.write({'invoice_policy': line[16] or False})

                            if line[23]:
                                try:
                                    u = urllib.request.urlopen(line[23])
                                    if u:
                                        image = u.read()
                                        image_base64 = base64.encodebytes(image)
                                        image_medium = image_base64
                                        imgs = self.create_img(image_medium, template)
                                except:
                                    _logger.warning('Issue in Import Image : Url is not found')

                            product_ids.write({
                                'taxes_id': [(4, tax_id) for tax_id in tax_id_lst],
                                'supplier_taxes_id': [(4, tax_id) for tax_id in supplier_taxes_id],
                                'public_categ_ids': [(6, 0, e_categ)]

                            })

                            for product in product_ids:
                                if product.type == 'product':
                                    company_user = self.env.user.company_id
                                    location = self.env['stock.warehouse'].search(
                                        [('company_id', '=', company_user.id)],
                                        limit=1).in_type_id.default_location_dest_id
                                    product = product.with_context(location=location.id)
                                    th_qty = product.qty_available

                                    Inventory = self.env['stock.quant']
                                    if quantity:
                                        inventory = Inventory.create({
                                            'product_id': product.id,
                                            'inventory_quantity': quantity,
                                            'location_id': location.id
                                        })

                                        inventory.action_apply_inventory()



                        else:
                            self.create_product(values)

            context = {'default_name': "%s Records Successfully Imported." % (row_no)
                       }
            _logger.info('XLS import completed successfully. Total records processed: %s', total_records)
            return {
                'name': 'Success',
                'type': 'ir.actions.act_window',
                'view_type': 'form',
                'view_mode': 'form',
                'res_model': 'custom.pop.message',
                'target': 'new',
                'context': context
            }
            return res

    def download_auto(self):
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/binary/download_document?model=gen.sale&id=%s' % (self.id),
            'target': 'new',
        }


class CustomPopMessage(models.TransientModel):
    _name = "custom.pop.message"
    _description = "Custom Pop Message"

    name = fields.Text('Message')
