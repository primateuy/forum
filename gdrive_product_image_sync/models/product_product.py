from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    gdrive_synced = fields.Boolean(
        string="Sincronizado con Google Drive",
        default=False,
        help="Indica que este variante ya tuvo una sincronización exitosa de imágenes desde Google Drive.",
    )

    variant_image_ids = fields.One2many(
        comodel_name="product.image",
        inverse_name="product_variant_id",
        string="Imágenes de variante",
    )

