import base64
import json
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
except ImportError:
    _logger.warning(
        "Google API libraries not installed. "
        "Install google-api-python-client and google-auth."
    )
    service_account = None
    build = None
    MediaIoBaseDownload = None

IMAGE_MIME_TYPES = [
    "image/jpeg",
    "image/png",
]

SCOPES = ["https://www.googleapis.com/auth/drive"]


class GDriveService(models.AbstractModel):
    _name = "gdrive.service"
    _description = "Google Drive Service"

    @api.model
    def _get_drive_client(self):
        """Build and return a Google Drive API client using service account credentials."""
        if service_account is None or build is None:
            _logger.error(
                "Google API libraries are not available. "
                "Cannot create Drive client."
            )
            return None

        config_param = self.env["ir.config_parameter"].sudo()
        sa_json = config_param.get_param(
            "gdrive_product_image_sync.service_account_json", default=""
        )
        if not sa_json:
            _logger.error(
                "Service account JSON not configured. "
                "Set 'gdrive_product_image_sync.service_account_json' in System Parameters."
            )
            return None

        try:
            sa_info = json.loads(sa_json)
            credentials = service_account.Credentials.from_service_account_info(
                sa_info, scopes=SCOPES
            )
            return build("drive", "v3", credentials=credentials, cache_discovery=False)
        except (json.JSONDecodeError, ValueError) as e:
            _logger.error("Invalid service account JSON: %s", e)
            return None
        except Exception as e:
            _logger.error("Failed to build Google Drive client: %s", e)
            return None

    @api.model
    def _list_images(self, folder_id):
        """List image files (.jpg, .jpeg, .png) in the specified Google Drive folder.

        Returns a list of dicts with 'id' and 'name' keys, or an empty list on error.
        """
        client = self._get_drive_client()
        if not client:
            return []

        mime_query = " or ".join(
            "mimeType='%s'" % mt for mt in IMAGE_MIME_TYPES
        )
        query = "'%s' in parents and (%s) and trashed=false" % (
            folder_id,
            mime_query,
        )

        _logger.info("Listing images in folder_id=%r with query: %s", folder_id, query)
        try:
            files = []
            page_token = None
            while True:
                response = (
                    client.files()
                    .list(
                        q=query,
                        fields="nextPageToken, files(id, name)",
                        pageSize=100,
                        pageToken=page_token,
                    )
                    .execute()
                )
                files.extend(response.get("files", []))
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
            _logger.info(
                "Found %d image(s) in Google Drive folder %s",
                len(files),
                folder_id,
            )
            return files
        except Exception as e:
            _logger.error(
                "Failed to list images in folder %s: %s", folder_id, e, exc_info=True
            )
            return []

    @api.model
    def _download_image(self, file_id):
        """Download a file from Google Drive and return its content as base64.

        Returns a base64-encoded string, or False on error.
        """
        client = self._get_drive_client()
        if not client:
            return False

        try:
            import io

            request = client.files().get_media(fileId=file_id)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return base64.b64encode(buffer.getvalue()).decode("utf-8")
        except Exception as e:
            _logger.error(
                "Failed to download file %s from Google Drive: %s",
                file_id,
                e,
            )
            return False

    @api.model
    def _get_or_create_processed_folder(self, parent_folder_id):
        """Find or create a 'processed' subfolder inside the given parent folder.

        Returns the folder ID, or False on error.
        """
        client = self._get_drive_client()
        if not client:
            return False

        try:
            query = (
                "'%s' in parents and name='processed' "
                "and mimeType='application/vnd.google-apps.folder' "
                "and trashed=false"
            ) % parent_folder_id
            response = (
                client.files()
                .list(q=query, fields="files(id)", pageSize=1)
                .execute()
            )
            existing = response.get("files", [])
            if existing:
                return existing[0]["id"]

            # Create the folder
            folder_metadata = {
                "name": "processed",
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_folder_id],
            }
            folder = (
                client.files()
                .create(body=folder_metadata, fields="id")
                .execute()
            )
            _logger.info(
                "Created 'processed' subfolder %s in folder %s",
                folder["id"],
                parent_folder_id,
            )
            return folder["id"]
        except Exception as e:
            _logger.error(
                "Failed to get/create processed folder in %s: %s",
                parent_folder_id,
                e,
            )
            return False

    @api.model
    def _move_to_processed(self, file_id, folder_id, destination_folder_id=None):
        """Move a file to the destination folder.

        If destination_folder_id is provided, moves directly to that folder.
        Otherwise falls back to creating/finding a 'processed' subfolder inside folder_id.

        Returns True on success, False on error.
        """
        if destination_folder_id:
            processed_folder_id = destination_folder_id
        else:
            processed_folder_id = self._get_or_create_processed_folder(folder_id)
        if not processed_folder_id:
            return False

        client = self._get_drive_client()
        if not client:
            return False

        try:
            # Get current parents to remove from them
            file_info = (
                client.files()
                .get(fileId=file_id, fields="parents")
                .execute()
            )
            previous_parents = ",".join(file_info.get("parents", []))

            client.files().update(
                fileId=file_id,
                addParents=processed_folder_id,
                removeParents=previous_parents,
                fields="id, parents",
            ).execute()
            _logger.info(
                "Moved file %s to processed folder %s",
                file_id,
                processed_folder_id,
            )
            return True
        except Exception as e:
            _logger.error(
                "Failed to move file %s to processed folder: %s",
                file_id,
                e,
            )
            return False
