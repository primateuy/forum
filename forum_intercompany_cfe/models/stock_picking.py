# -*- coding: utf-8 -*-
from odoo import fields, models


class StockPicking(models.Model):
    """Permite emitir el e-Remito/CFE bajo el RUT (company fiscal) correcto
    aunque la company operativa del picking sea otra, e incorpora la referencia
    logística de los paquetes al documento.

    Contexto Forum: una sola company operativa (FORUM) explota tiendas que
    legalmente emiten bajo distintos RUTs (Faringol SA, Neratur SA, etc.). El
    `dgi.punto.emision` (y su `dgi.sucursal`) pertenecen a la company legal de la
    tienda; FORUM ni siquiera tiene la FE activa. Por eso:

    1. El picking de FORUM debe poder llevar el punto de emisión de Faringol
       (relajamos `check_company` de `punto_emision_id`).
    2. La emisión del CFE debe correr en el contexto de la company FISCAL para
       que tome SUS credenciales/URL/modo (`get_param` usa `self.env.company`) y
       SU RUT/Razón Social en el XML (el template usa `docargs['company']`).
    3. La Adenda del e-Remito expone el `name` de los `stock.quant.package`
       asociados al picking, como referencia logística operativa (los crea WIS
       — este módulo sólo los expone, no los genera).

    Diseño temporal y no invasivo per spec: todo vía herencia, sin modificar el
    core ni `LocalizacionUy`; desinstalando el módulo se restaura el
    comportamiento estándar.
    """
    _inherit = 'stock.picking'

    # Punto 1: el punto de emisión es el emisor FISCAL y legítimamente puede
    # pertenecer a otra company que la operativa del documento. Re-declaramos
    # SOLO este atributo; compute/store/domain se heredan de l10n_uy_einvoice_base.
    punto_emision_id = fields.Many2one(check_company=False)

    def _forum_cfe_fiscal_company(self):
        """Company FISCAL que debe emitir el CFE: la del punto de emisión.
        Cae a `company_id` si no hay punto (caso normal mono-RUT)."""
        self.ensure_one()
        return self.punto_emision_id.company_id or self.company_id

    def create_delivery_guide(self):
        """Emite el e-Remito en el contexto de la company FISCAL (la del punto de
        emisión), no la operativa. Así `get_param()` toma credenciales, URL y
        modo (testing/live) del RUT correcto aunque el picking sea de FORUM."""
        res = True
        for picking in self:
            fiscal = picking._forum_cfe_fiscal_company()
            res = super(StockPicking, picking.with_company(fiscal)).create_delivery_guide()
        return res

    def get_armed_docargs_remito(self, cfe_type):
        """Fuerza que el RUT y la Razón Social del emisor en el XML sean los de
        la company fiscal del punto de emisión (el template hace
        `RUCEmisor t-out="company.vat"`), no los de la company operativa."""
        docargs = super().get_armed_docargs_remito(cfe_type)
        fiscal = self._forum_cfe_fiscal_company()
        if fiscal:
            docargs['company'] = fiscal
        return docargs

    def _get_emisor_partner(self):
        """Domicilio fiscal del emisor: prioriza la dirección de la sucursal DGI;
        si no tiene, cae al partner de la company FISCAL (no la operativa)."""
        self.ensure_one()
        sucursal = getattr(self, 'dgi_sucursal_id', False)
        if sucursal and sucursal.direccion_partner_id:
            return sucursal.direccion_partner_id
        return self._forum_cfe_fiscal_company().partner_id

    def _get_remito_adenda(self):
        """Expone la referencia logística de los paquetes en la Adenda del e-Remito.

        Spec "Módulo de Emisión Intercompany Temporal" / "Información adicional en
        remitos": el operario debe poder identificar físicamente el bulto durante
        despacho/recepción desde el remito. Como los `stock.quant.package` de este
        Odoo no tienen código de barras propio, el único identificador disponible
        es el `name` del paquete (lo genera WIS al recibir el contenedor — este
        módulo NO crea paquetes, sólo expone su nombre en el documento).

        Se agrega como suplemento de la adenda existente (super()) para no perder
        las observaciones que ya pueda traer el picking.
        """
        base_adenda = super()._get_remito_adenda() or ''
        paquetes = self.move_line_ids.result_package_id.sorted('name')
        referencias = ', '.join(p.name for p in paquetes if p.name)
        if not referencias:
            return base_adenda
        bloque = f"Paquetes: {referencias}"
        return f"{base_adenda}\n{bloque}" if base_adenda else bloque
