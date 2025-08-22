from odoo import api, models, fields;
from odoo.exceptions import ValidationError



class NivelesJerarquia(models.Model):
    _name = 'niveles.jerarquia';
    _description = 'Niveles de Jerarquia';


    nombre = fields.Char(string="Nombre", required=True);

    seq = fields.Integer(required=True, string="Número de sequencia", default=1, help="Mientras menor el número, mayor la jerarquia");
    grupos_id = fields.One2many('stock.warehouse.group', 'nivel_jerarquia_id', string='Grupos de Almacenes', required=True)
    
    
    
    

    @api.model
    def create(self, vals):


        if not 'seq' in vals:
            raise ValidationError("Verifique el número de sequencia");

        if 'seq' in vals and vals['seq'] < 1:
            raise ValidationError("El número no puede ser menor a 1");

        return super().create(vals);

    @api.model
    def write(self, vals):
    
        if 'seq' in vals and vals['seq'] < 1:
            raise ValidationError("El número no puede ser menor a 1");

        
        return super().write(vals);

    