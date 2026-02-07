"""
sdr/tools/bigquery_utils.py
BigQuery helpers for persisting SDR session data.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from common.config import (
    GOOGLE_CLOUD_PROJECT,
    BIGQUERY_DATASET,
    BIGQUERY_SDR_SESSIONS_TABLE,
    BIGQUERY_LEADS_TABLE,
)

logger = logging.getLogger(__name__)

SDR_SCHEMA = [
    {"name": "session_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "lead_place_id", "type": "STRING"},
    {"name": "business_name", "type": "STRING"},
    {"name": "research_summary", "type": "STRING"},
    {"name": "proposal_summary", "type": "STRING"},
    {"name": "call_transcript", "type": "STRING"},
    {"name": "call_outcome", "type": "STRING"},
    {"name": "email_sent", "type": "BOOLEAN"},
    {"name": "email_subject", "type": "STRING"},
    {"name": "created_at", "type": "TIMESTAMP"},
]


def _get_client():
    try:
        from google.cloud import bigquery
        return bigquery.Client(project=GOOGLE_CLOUD_PROJECT)
    except Exception as e:
        logger.error(f"BigQuery client init failed: {e}")
        return None


def save_sdr_session(session_data: dict[str, Any]) -> str:
    """
    Persist an SDR session record to BigQuery.

    Args:
        session_data: Dict matching SDR_SCHEMA fields.

    Returns:
        JSON string with result.
    """
    client = _get_client()
    if not client:
        return json.dumps({"success": False, "error": "BigQuery unavailable"})

    table_ref = f"{GOOGLE_CLOUD_PROJECT}.{BIGQUERY_DATASET}.{BIGQUERY_SDR_SESSIONS_TABLE}"
    try:
        errors = client.insert_rows_json(table_ref, [session_data])
        if errors:
            return json.dumps({"success": False, "errors": [str(e) for e in errors]})
        return json.dumps({"success": True, "session_id": session_data.get("session_id")})
    except Exception as e:
        logger.error(f"SDR session save failed: {e}")
        return json.dumps({"success": False, "error": str(e)})


def update_lead_status(place_id: str, new_status: str) -> str:
    """
    Update a lead's status in BigQuery.

    Args:
        place_id: The lead's place_id.
        new_status: New status value.

    Returns:
        JSON result.
    """
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
        return json.dumps({"success": True, "place_id": place_id, "new_status": new_status})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})
