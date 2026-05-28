# -*- coding: utf-8 -*-
{
    'name': 'FORUM - Inter-company CFE / e-Remito',
    'version': '17.0.1.0.0',
    'category': 'Localization/Uruguay',
    'summary': 'Permite emitir CFE/e-Remitos bajo el RUT (punto de emisión) correcto '
               'aunque la company operativa del documento sea otra',
    'description': """
FORUM - Inter-company CFE / e-Remito
====================================

Implementa el spec "Módulo de Emisión Intercompany Temporal":

En el setup de Forum, una sola company operativa (FORUM) explota tiendas que
legalmente facturan bajo distintos RUTs (Faringol SA, Neratur SA, etc.). Cada
tienda es una `dgi.sucursal` + `dgi.punto.emision` que pertenecen a la company
legal correspondiente, NO a FORUM.

El módulo permite que la emisión del e-Remito use los datos documentales, la
configuración electrónica y la identidad fiscal de la company asociada a la
sucursal seleccionada en Facturación Electrónica (no la del Tipo de Operación):

1. Destraba `check_company` del campo `punto_emision_id` → habilita asignar un
   punto de emisión de otra company.
2. Override de `create_delivery_guide` → envía la CFE `with_company(fiscal)`,
   tomando credenciales / URL / modo (testing-live) de la company fiscal.
3. Override de `get_armed_docargs_remito` → en el XML del e-Remito, el
   `RUCEmisor` y `RznSoc` salen de la company fiscal.
4. Override de `_get_emisor_partner` → el domicilio fiscal cae al partner de la
   company fiscal si la sucursal DGI no tiene `direccion_partner_id`.
5. Override de `_get_remito_adenda` → expone en la Adenda del CFE el `name` de
   los `stock.quant.package` del picking (referencia logística operativa). Los
   paquetes los crea WIS (`integracion_wis`); este módulo solo los expone.

Diseño temporal y no invasivo: todo vía herencia, sin tocar `LocalizacionUy`
ni el core; desinstalando el módulo se restaura el comportamiento estándar
(ownership de stock, lógica contable y flujo intercompany NO se modifican).
    """,
    'author': 'Primate',
    'website': 'https://primateuy.odoo.com',
    'depends': [
        'stock',
        'l10n_uy_einvoice_base',
        # Necesario para que los overrides de emisión (create_delivery_guide,
        # get_armed_docargs_remito) queden por encima en el MRO.
        'l10n_uy_einvoice_uruware',
    ],
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
