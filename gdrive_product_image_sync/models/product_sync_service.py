import base64
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
    def _apply_images_to_variants(self, variants, images_by_position, names_by_position=None):
        """Write images directly to product.product variants.
        Position 1  -> image_variant_1920 on each variant (stored field, avoids _inherits delegation)
        Position >1 -> product.image records linked to the template (once, no duplicates)
        """
        if names_by_position is None:
            names_by_position = {}

        if 1 in images_by_position:
            for variant in variants:
                variant.write({"image_variant_1920": images_by_position[1]})

        extra = [
            (pos, img)
            for pos, img in sorted(images_by_position.items())
            if pos != 1
        ]
        if extra:
            for pos, img in extra:
                name = names_by_position.get(pos) or "Image %d" % pos
                for variant in variants:
                    self.env["product.image"].create({
                        "product_variant_id": variant.id,
                        "product_tmpl_id": variant.product_tmpl_id.id,
                        "image_1920": img,
                        "name": name,
                        "sequence": pos * 10,
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
        """Main orchestrator: list images, match by SKU, update products, move files.

        Processes SKU groups in batches to limit RAM usage. After each batch,
        successfully processed files are moved and the ORM cache is cleared.
        """
        config_param = self.env["ir.config_parameter"].sudo()
        folder_id_raw = config_param.get_param(
            "gdrive_product_image_sync.folder_id", default=""
        )
        folder_id = self._extract_folder_id(folder_id_raw) if folder_id_raw else ""
        if not folder_id:
            _logger.warning("Google Drive folder ID not configured. Skipping sync.")
            return

        move_after_sync = config_param.get_param(
            "gdrive_product_image_sync.move_after_sync", default="False"
        ) == "True"

        processed_folder_id_raw = config_param.get_param(
            "gdrive_product_image_sync.processed_folder_id", default=""
        )
        processed_folder_id = self._extract_folder_id(processed_folder_id_raw) if processed_folder_id_raw else None

        batch_size = int(config_param.get_param(
            "gdrive_product_image_sync.batch_size", default=10
        ) or 10)

        images = self._list_images(folder_id)
        if not images:
            _logger.info("No images to sync.")
            return

        total_images = len(images)
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
                SyncLog.create({
                    "name": img["name"],
                    "sku": base_key,
                    "status": "warning",
                    "message": "Filename does not match expected pattern 'CODE-N.ext'",
                })
                continue
            groups[base_key][position] = img

        all_variants = self.env["product.product"].search(
            [("default_code", "!=", False)]
        )

        group_items = list(groups.items())
        total_groups = len(group_items)
        processed_count = 0

        for batch_start in range(0, total_groups, batch_size):
            batch = group_items[batch_start:batch_start + batch_size]
            batch_files_to_move = []

            _logger.info(
                "Processing batch %d-%d of %d SKU groups.",
                batch_start + 1,
                min(batch_start + batch_size, total_groups),
                total_groups,
            )

            for base_key, pos_files in batch:
                variants = all_variants.filtered(
                    lambda v: self._normalize_variant_sku(v.default_code) == base_key
                )
                if not variants:
                    continue

                # Si todas las variantes ya están sincronizadas, solo mover si corresponde
                if all(v.gdrive_synced for v in variants):
                    if move_after_sync:
                        for img in pos_files.values():
                            batch_files_to_move.append(img["id"])
                        _logger.info(
                            "SKU '%s' ya sincronizado — solo moviendo %d archivo(s).",
                            base_key,
                            len(pos_files),
                        )
                    else:
                        _logger.info(
                            "SKU '%s' ya sincronizado — omitiendo.",
                            base_key,
                        )
                    continue

                # Download each image in this group
                images_by_position = {}
                names_by_position = {}
                for pos, img in pos_files.items():
                    image_base64 = self._download_image(img["id"])
                    if not image_base64:
                        SyncLog.create({
                            "name": img["name"],
                            "sku": base_key,
                            "status": "error",
                            "message": "Failed to download image from Google Drive",
                        })
                        _logger.error("Sync error — %s: download failed", img["name"])
                        continue
                    images_by_position[pos] = image_base64
                    names_by_position[pos] = os.path.splitext(img["name"])[0]

                if not images_by_position:
                    continue

                self._apply_images_to_variants(variants, images_by_position, names_by_position)

                # Marcar variantes como sincronizadas
                variants.write({"gdrive_synced": True})

                for pos, img in pos_files.items():
                    if pos not in images_by_position:
                        continue
                    target_field = "image_1920" if pos == 1 else "product_template_image_ids"
                    template_name = variants.mapped("product_tmpl_id")[0].name
                    SyncLog.create({
                        "name": img["name"],
                        "sku": base_key,
                        "status": "ok",
                        "message": "Applied to '%s' → %s" % (template_name, target_field),
                    })
                    batch_files_to_move.append(img["id"])
                    processed_count += 1
                    _logger.info(
                        "Sync OK — %s → template '%s' (%s)",
                        img["name"],
                        template_name,
                        target_field,
                    )

                # Liberar memoria de las imágenes descargadas en este SKU
                del images_by_position

            # Mover archivos del lote si está habilitado
            if move_after_sync:
                for file_id in batch_files_to_move:
                    self._move_to_processed(file_id, folder_id, destination_folder_id=processed_folder_id)

            self.env.cr.commit()
            self.env.invalidate_all()
            _logger.info(
                "Batch committed. %d/%d images processed so far.",
                processed_count,
                total_images,
            )

        _logger.info(
            "Sync complete: %d of %d image(s) processed.",
            processed_count,
            total_images,
        )