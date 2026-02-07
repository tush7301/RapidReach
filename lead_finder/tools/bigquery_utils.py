"""
lead_finder/tools/bigquery_utils.py
BigQuery helpers for persisting discovered leads.
Creates dataset/table if needed, uploads batched rows.
"""

from __future__ import annotations
import json
import logging
from typing import Any

from common.config import (
    GOOGLE_CLOUD_PROJECT,
    BIGQUERY_DATASET,
    BIGQUERY_LEADS_TABLE,
)

logger = logging.getLogger(__name__)

LEADS_SCHEMA = [
    {"name": "place_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "business_name", "type": "STRING"},
    {"name": "address", "type": "STRING"},
    {"name": "city", "type": "STRING"},
    {"name": "phone", "type": "STRING"},
    {"name": "email", "type": "STRING"},
    {"name": "website", "type": "STRING"},
    {"name": "rating", "type": "FLOAT"},
    {"name": "total_ratings", "type": "INTEGER"},
    {"name": "business_type", "type": "STRING"},
    {"name": "has_website", "type": "BOOLEAN"},
    {"name": "lead_status", "type": "STRING"},
    {"name": "discovered_at", "type": "TIMESTAMP"},
    {"name": "notes", "type": "STRING"},
]


def _get_client():
    """Lazy-load BigQuery client."""
    try:
        from google.cloud import bigquery
        return bigquery.Client(project=GOOGLE_CLOUD_PROJECT)
    except Exception as e:
        logger.error(f"BigQuery client init failed: {e}")
        return None


def ensure_table_exists() -> bool:
    """Create dataset and table if they don't exist."""
    client = _get_client()
    if not client:
        return False
    try:
        from google.cloud import bigquery

        dataset_ref = f"{GOOGLE_CLOUD_PROJECT}.{BIGQUERY_DATASET}"
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "US"
        client.create_dataset(dataset, exists_ok=True)

        table_ref = f"{dataset_ref}.{BIGQUERY_LEADS_TABLE}"
        schema = [
            bigquery.SchemaField(f["name"], f["type"], mode=f.get("mode", "NULLABLE"))
            for f in LEADS_SCHEMA
        ]
        table = bigquery.Table(table_ref, schema=schema)
        client.create_table(table, exists_ok=True)
        logger.info(f"Table {table_ref} ready")
        return True
    except Exception as e:
        logger.error(f"ensure_table_exists failed: {e}")
        return False


def upload_leads(leads: list[dict[str, Any]]) -> str:
    """
    Upload a batch of leads to BigQuery.

    Args:
        leads: List of lead dicts matching LEADS_SCHEMA.

    Returns:
        JSON string with result summary.
    """
    if not leads:
        return json.dumps({"uploaded": 0, "errors": []})

    client = _get_client()
    if not client:
        return json.dumps({"uploaded": 0, "errors": ["BigQuery client unavailable"]})

    ensure_table_exists()
    table_ref = f"{GOOGLE_CLOUD_PROJECT}.{BIGQUERY_DATASET}.{BIGQUERY_LEADS_TABLE}"

    errors_list = []
    try:
        result = client.insert_rows_json(table_ref, leads)
        if result:
            errors_list = [str(e) for e in result]
            logger.warning(f"BQ insert errors: {errors_list}")
    except Exception as e:
        errors_list.append(str(e))
        logger.error(f"BQ upload failed: {e}")

    uploaded = len(leads) - len(errors_list)
    return json.dumps({"uploaded": uploaded, "errors": errors_list})
