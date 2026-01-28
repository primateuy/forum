import logging
import requests
import pytz

from datetime import datetime, timedelta
from dateutil import parser
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class ApiKsi(models.AbstractModel):
    _name = "api.ksi"
    _description = "API KSI"

    # -------------------------------------------------------
    # CRON – Sincronización
    # -------------------------------------------------------
    @api.model
    def run_cron_sync_ksi_traffic(self):
        companies_ids = self.env["res.company"].search([])
        for company_id in companies_ids:
            self.sync_data_in_company(company_id)

    def sync_data_in_company(self, company_id):
        journals_ids = self.env["account.journal"].search([
            ("company_id", "=", company_id.id),
            ("id_ksi_locations_group", "!=", False)
        ])

        for journal_id in journals_ids:
            self.update_journal_ksi_data(journal_id)

    def update_journal_ksi_data(self, journal_id):
        base_url = self.env['ir.config_parameter'].sudo().get_param('ksi_integration.base_url')
        token = self.env['ir.config_parameter'].sudo().get_param('ksi_integration.token_api')

        url = f"{base_url}/locations_group/{journal_id.id_ksi_locations_group}/kpis/traffic-total"

        headers = {
            "Authorization": f"Bearer {token}"
        }

        def call_api(params):
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            return response.json()

        utc_now = fields.Datetime.now()
        utc_now = pytz.utc.localize(utc_now)

        tz_name = 'America/Montevideo'
        local_tz = pytz.timezone(tz_name)

        to_time_local = utc_now.astimezone(local_tz)
        from_time_local = to_time_local - timedelta(hours=24)

        to_time_str = to_time_local.isoformat()
        from_time_str = from_time_local.isoformat()

        try:
            visitors_data = call_api({
                "timeBucket": "1 hour",
                "fromTime": from_time_str,
                "toTime": to_time_str,
                "isEntrance": "true",
                "page": 0,
                "size": 200
            })

            external_data = call_api({
                "timeBucket": "1 hour",
                "fromTime": from_time_str,
                "toTime": to_time_str,
                "isExternalFlow": "true",
                "page": 0,
                "size": 200
            })

        except Exception as e:
            _logger.error("Error consultando KSI (%s): %s", journal_id, e)
            return

        visitors_data_mapping = {
            r["time"]: r['sum_forwards']
            for r in visitors_data.get("items", [])
        }

        visitors_external_data_mapping = {
            r["time"]: r['sum_forwards']
            for r in external_data.get("items", [])
        }

        joined_map = {
            k: (visitors_data_mapping.get(k, 0), visitors_external_data_mapping.get(k, 0))
            for k in visitors_data_mapping.keys() | visitors_external_data_mapping.keys()
        }

        id_company = journal_id.company_id.id
        id_journal = journal_id.id

        keys = list(joined_map.keys())
        record_already_exists_ids = self.env['ksi.traffic'].search([
            ("journal_id", "=", id_journal),
            ("time_code", "in", keys)
        ])
        key_already_exists = record_already_exists_ids.mapped("time_code")

        for key, data in joined_map.items():
            vals = {
                'sum_forwards_is_entrance': data[0],
                'sum_forwards_is_external_flow': data[1],
                'last_ws_update': fields.Datetime.now(),
            }

            if key in key_already_exists:
                r = record_already_exists_ids.filtered(lambda r: r.time_code == key)
                r.write(vals)
            else:
                time_key = key
                dt_local = parser.isoparse(time_key)

                date_odoo = dt_local.date()
                hour_odoo = dt_local.strftime("%H:00")

                dt_utc = dt_local.astimezone(pytz.utc)

                dt_odoo = dt_utc.replace(tzinfo=None)

                vals.update({
                    "company_id": id_company,
                    "journal_id": id_journal,
                    "fecha_hora": dt_odoo,
                    "fecha": date_odoo,
                    "hora": hour_odoo,
                    "time_code": key,
                })
                new_id = self.env['ksi.traffic'].create([vals])
                # record_already_exists_ids += new_id
                # key_already_exists += [key]
