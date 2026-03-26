import logging
import os
import re
from collections import defaultdict

from odoo import api, models

_logger = logging.getLogger(__name__)


class ProductSyncService(models.AbstractModel):
    _name = "product.sync.service"
    _inherit = "gdrive.service"
    _description = "Product Image Sync Service"

    @api.model
    def _parse_filename(self, filename):
        """Extract base comparison key and image position from a drive filename.

        Logic:
          - Strip extension
          - Split on last '-' to get (base_with_dashes, position_str)
          - Remove dashes from base for comparison
          - Position determines target field: 1 -> image_1920, others -> product_template_image_ids

        E.g. 'CAMISA-001-1.jpg' -> ('CAMISA001', 1)
             'CAMISA-001-2.jpg' -> ('CAMISA001', 2)

        Returns (base_key, position) or (name_no_ext, None) if format doesn't match.
        """
        name = os.path.splitext(filename)[0]
        parts = name.rsplit("-", 1)
        if len(parts) == 2 and parts[1].isdigit():
            base_key = parts[0].replace("-", "")
            return base_key, int(parts[1])
        return name.replace("-", ""), None

    @api.model
    def _normalize_variant_sku(self, default_code):
        """Remove last 3 characters and dashes from a variant internal reference.

        E.g. 'CAMISA001RED' -> 'CAMISA001'
             'CAMISA-001-RED' -> 'CAMISA001'
        """
        trimmed = default_code[:-3] if len(default_code) > 3 else default_code
        return trimmed.replace("-", "")

    @api.model
    def _find_variants_by_base_key(self, base_key):
        """Find product.product variants whose normalized default_code matches base_key.

        Returns a recordset (possibly empty).
        """
        variants = self.env["product.product"].search(
            [("default_code", "!=", False)]
        )
        return variants.filtered(
            lambda v: self._normalize_variant_sku(v.default_code) == base_key
        )

    @api.model
    def _apply_images_to_variants(self, variants, images_by_position):
        """Write images directly to product.product variants.
        Position 1  -> image_variant_1920 on each variant (stored field, avoids _inherits delegation)
        Position >1 -> product.image records linked to the template (once, no duplicates)
        """
        if 1 in images_by_position:
            for variant in variants:
                variant.write({"image_variant_1920": images_by_position[1]})

        extra = [
            (pos, img)
            for pos, img in sorted(images_by_position.items())
            if pos != 1
        ]
        if extra:
            template = variants.mapped("product_tmpl_id")[0]
            for variant in variants:
                for pos, img in extra:
                    self.env["product.image"].create({
                        "product_tmpl_id": template.id,
                        "product_variant_id": variant.id,
                        "image_1920": img,
                        "name": "Image %d" % pos,
                    })

    @api.model
    def _extract_folder_id(self, folder_id_or_url):
        """Extract folder ID from a Google Drive URL or return the value as-is."""
        match = re.search(r"/folders/([a-zA-Z0-9_-]+)", folder_id_or_url)
        if match:
            return match.group(1)
        return folder_id_or_url.strip()

    @api.model
    def _sync_images_from_drive(self):
        """Main orchestrator: list images, match by SKU, update products, move files."""
        config_param = self.env["ir.config_parameter"].sudo()
        folder_id_raw = config_param.get_param(
            "gdrive_product_image_sync.folder_id", default=""
        )
        folder_id = self._extract_folder_id(folder_id_raw) if folder_id_raw else ""
        if not folder_id:
            _logger.warning("Google Drive folder ID not configured. Skipping sync.")
            return

        images = self._list_images(folder_id)
        if not images:
            _logger.info("No images to sync.")
            return

        SyncLog = self.env["gdrive.sync.log"]

        # --- Group drive files by base key ---
        # groups[base_key] = {position: file_dict}
        groups = defaultdict(dict)
        for img in images:
            base_key, position = self._parse_filename(img["name"])
            if position is None:
                _logger.warning(
                    "Cannot parse position from '%s' (expected 'CODE-N.ext'). Skipping.",
                    img["name"],
                )
                SyncLog.create(
                    {
                        "name": img["name"],
                        "sku": base_key,
                        "status": "warning",
                        "message": "Filename does not match expected pattern 'CODE-N.ext'",
                    }
                )
                continue
            groups[base_key][position] = img

        processed_count = 0
        files_to_move = []  # list of file_ids that succeeded
        orignial_variants = self.env["product.product"].search(
            [("default_code", "!=", False)]
        )
        for base_key, pos_files in groups.items():
            # ME TRAIGO LAS VARIANTES QUE COINCIDAN CON EL BASE_KEY, SI NO HAY NINGUNA, LOGUEO Y CONTINUO CON EL SIGUIENTE GRUPO
            variants =  orignial_variants.filtered(
                lambda v: self._normalize_variant_sku(v.default_code) == base_key
            )
            if not variants:
                continue

            # Download each image in this group
            images_by_position = {}
            for pos, img in pos_files.items():
                image_base64 = self._download_image(img["id"])
                if not image_base64:
                    SyncLog.create(
                        {
                            "name": img["name"],
                            "sku": base_key,
                            "status": "error",
                            "message": "Failed to download image from Google Drive",
                        }
                    )
                    _logger.error("Sync error — %s: download failed", img["name"])
                    continue
                images_by_position[pos] = image_base64

            if not images_by_position:
                continue

            # Apply all downloaded images to the variants
            self._apply_images_to_variants(variants, images_by_position)

            # Log success and queue files for move
            for pos, img in pos_files.items():
                if pos not in images_by_position:
                    continue
                target_field = "image_1920" if pos == 1 else "product_template_image_ids"
                template_name = variants.mapped("product_tmpl_id")[0].name
                SyncLog.create(
                    {
                        "name": img["name"],
                        "sku": base_key,
                        "status": "ok",
                        "message": "Applied to '%s' → %s" % (template_name, target_field),
                    }
                )
                files_to_move.append(img["id"])
                processed_count += 1
                _logger.info(
                    "Sync OK — %s → template '%s' (%s)",
                    img["name"],
                    template_name,
                    target_field,
                )

        # Move all successfully processed files to 'processed' subfolder
        for file_id in files_to_move:
            self._move_to_processed(file_id, folder_id)

        _logger.info(
            "Sync complete: %d of %d image(s) processed.",
            processed_count,
            len(images),
        )