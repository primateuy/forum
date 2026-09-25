# -*- coding: utf-8 -*-
"""Costo del producto: seguridad real, no cosmética.

`generic_security_restriction` oculta campos inyectando `invisible` en
`_postprocess_tag_field`, o sea que actúa sobre los nodos `<field>` de la vista. Eso
alcanza para lo que es de presentación, pero no para el costo:

- El `invisible` del arch **no saca el campo de `fields_get`**. En una vista pivot el
  usuario abre el desplegable de Medidas y agrega la medida de costo a mano.
- Tampoco impide un `read` por RPC, ni una exportación, ni un filtro.

El atributo `groups=` nativo sí: Odoo lo aplica en `fields_get` y en el `read` del ORM,
así que el campo no se lee, no viaja al cliente y no aparece entre las medidas.

En core `standard_price` trae `groups="base.group_user"`, o sea todos los usuarios
internos. Acá se estrecha a un grupo propio. La migración se lo otorga a todos los
usuarios internos actuales menos los del perfil sucursal, así que el día del deploy no
cambia nada para nadie.
"""
from odoo import models, fields

COST_GROUP = 'forum_branch_security.group_product_cost'


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    standard_price = fields.Float(groups=COST_GROUP)
    # Costo en moneda de reportería, de tchistorico.
    ultimo_costo_mr = fields.Float(groups=COST_GROUP)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    standard_price = fields.Float(groups=COST_GROUP)
    ultimo_costo_mr = fields.Float(groups=COST_GROUP)
