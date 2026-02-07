"""
lead_manager/tools/bigquery_utils.py
BigQuery helpers for Lead Manager:
  - Check if a sender is a known/hot lead
  - Persist meeting records
  - Update lead status
"""

from __future__ import annotations

import json
import logging
from typing import Any

from common.config import (
    GOOGLE_CLOUD_PROJECT,
    BIGQUERY_DATASET,
    BIGQUERY_LEADS_TABLE,
    BIGQUERY_MEETINGS_TABLE,
)

logger = logging.getLogger(__name__)


def _get_client():
    try:
        from google.cloud import bigquery
        return bigquery.Client(project=GOOGLE_CLOUD_PROJECT)
    except Exception as e:
        logger.error(f"BigQuery client init failed: {e}")
        return None


async def check_if_known_lead(sender_email: str) -> str:
    """
    Check if an email sender matches a known lead in BigQuery.

    Args:
        sender_email: The sender's email address.

    Returns:
        JSON with lead info if found, or indication of unknown sender.
    """
    client = _get_client()
    if not client:
        return json.dumps({"is_known": False, "error": "BigQuery unavailable"})

    table_ref = f"{GOOGLE_CLOUD_PROJECT}.{BIGQUERY_DATASET}.{BIGQUERY_LEADS_TABLE}"
    query = f"""
        SELECT place_id, business_name, lead_status, phone, email, city
        FROM `{table_ref}`
        WHERE email = @sender_email
        LIMIT 1
    """
    try:
        from google.cloud import bigquery as bq
        job_config = bq.QueryJobConfig(
            query_parameters=[
                bq.ScalarQueryParameter("sender_email", "STRING", sender_email),
            ]
        )
        rows = list(client.query(query, job_config=job_config).result())
        if rows:
            row = dict(rows[0])
            return json.dumps({
                "is_known": True,
                "place_id": row.get("place_id", ""),
                "business_name": row.get("business_name", ""),
                "lead_status": row.get("lead_status", ""),
                "phone": row.get("phone", ""),
                "email": row.get("email", ""),
                "city": row.get("city", ""),
            })
        return json.dumps({"is_known": False})
    except Exception as e:
        logger.warning(f"Lead lookup failed: {e}")
        return json.dumps({"is_known": False, "error": str(e)})


def save_meeting(meeting_data: dict[str, Any]) -> str:
    """
    Persist a meeting record to BigQuery.

    Args:
        meeting_data: Meeting dict with fields matching meetings schema.

    Returns:
        JSON result.
    """
    client = _get_client()
    if not client:
        return json.dumps({"success": False, "error": "BigQuery unavailable"})

    table_ref = f"{GOOGLE_CLOUD_PROJECT}.{BIGQUERY_DATASET}.{BIGQUERY_MEETINGS_TABLE}"
    try:
        errors = client.insert_rows_json(table_ref, [meeting_data])
        if errors:
            return json.dumps({"success": False, "errors": [str(e) for e in errors]})
        return json.dumps({"success": True})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def update_lead_status(place_id: str, new_status: str) -> str:
    """Update a lead's status in BigQuery."""
    client = _get_client()
    if not client:
        return json.dumps({"success": False, "error": "BigQuery unavailable"})

    table_ref = f"{GOOGLE_CLOUD_PROJECT}.{BIGQUERY_DATASET}.{BIGQUERY_LEADS_TABLE}"
    query = f"""
        UPDATE `{table_ref}`
        SET lead_status = @new_status
        WHERE place_id = @place_id
    """
    try:
        from google.cloud import bigquery as bq
        job_config = bq.QueryJobConfig(
            query_parameters=[
                bq.ScalarQueryParameter("new_status", "STRING", new_status),
                bq.ScalarQueryParameter("place_id", "STRING", place_id),
            ]
        )
        client.query(query, job_config=job_config).result()
        return json.dumps({"success": True})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})
