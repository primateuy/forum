# -*- coding: utf-8 -*-
from . import controllers
from . import models



def post_init_hook(env):
    
    # Obtener todos los almacenes que no tengan crossdocking_location_id
    warehouses = env['stock.warehouse'].search([
        ('crossdocking_location_id', '=', False)
    ])
    
    if warehouses:
        # Crear ubicaciones de crossdocking para cada almacén
        warehouses._create_crossdocking_location()
