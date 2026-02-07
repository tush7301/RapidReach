"""
common/config.py
Central configuration: ports, URLs, artifact names, and env helpers.
All services import from here so defaults are consistent.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Service Ports ────────────────────────────────────────────
LEAD_FINDER_PORT = int(os.getenv("LEAD_FINDER_PORT", "8081"))
LEAD_MANAGER_PORT = int(os.getenv("LEAD_MANAGER_PORT", "8082"))
GMAIL_LISTENER_PORT = int(os.getenv("GMAIL_LISTENER_PORT", "8083"))
SDR_PORT = int(os.getenv("SDR_PORT", "8084"))
UI_CLIENT_PORT = int(os.getenv("UI_CLIENT_PORT", "8000"))

# ── Service URLs ─────────────────────────────────────────────
LEAD_FINDER_SERVICE_URL = os.getenv("LEAD_FINDER_SERVICE_URL", f"http://localhost:{LEAD_FINDER_PORT}")
LEAD_MANAGER_SERVICE_URL = os.getenv("LEAD_MANAGER_SERVICE_URL", f"http://localhost:{LEAD_MANAGER_PORT}")
GMAIL_LISTENER_SERVICE_URL = os.getenv("GMAIL_LISTENER_SERVICE_URL", f"http://localhost:{GMAIL_LISTENER_PORT}")
SDR_SERVICE_URL = os.getenv("SDR_SERVICE_URL", f"http://localhost:{SDR_PORT}")
UI_CLIENT_URL = os.getenv("UI_CLIENT_URL", f"http://localhost:{UI_CLIENT_PORT}")

# ── Artifact Names (main result payloads) ────────────────────
LEAD_FINDER_ARTIFACT = "lead_results"
LEAD_MANAGER_ARTIFACT = "lead_management_decision"
SDR_ARTIFACT = "sdr_decision"

# ── BigQuery ─────────────────────────────────────────────────
BIGQUERY_DATASET = os.getenv("BIGQUERY_DATASET", "salesshortcut")
BIGQUERY_LEADS_TABLE = os.getenv("BIGQUERY_LEADS_TABLE", "leads")
BIGQUERY_MEETINGS_TABLE = os.getenv("BIGQUERY_MEETINGS_TABLE", "meetings")
BIGQUERY_SDR_SESSIONS_TABLE = os.getenv("BIGQUERY_SDR_SESSIONS_TABLE", "sdr_sessions")
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")

# ── LLM Models ───────────────────────────────────────────────
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "openai/gpt-4.1")
RESEARCH_MODEL = os.getenv("RESEARCH_MODEL", "openai/gpt-4.1")
CLASSIFIER_MODEL = os.getenv("CLASSIFIER_MODEL", "openai/gpt-4.1")
DRAFT_MODEL = os.getenv("DRAFT_MODEL", "anthropic/claude-sonnet-4-20250514")

# ── Email / Gmail ────────────────────────────────────────────
SALES_EMAIL = os.getenv("SALES_EMAIL", "")
SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE", "")  # kept for BigQuery

# ── OAuth2 (for personal Gmail + Calendar) ───────────────────
OAUTH_CREDENTIALS_FILE = os.getenv("OAUTH_CREDENTIALS_FILE", "./credentials/oauth_credentials.json")
OAUTH_TOKEN_FILE = os.getenv("OAUTH_TOKEN_FILE", "./credentials/token.json")

# ── ElevenLabs ───────────────────────────────────────────────
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")
ELEVENLABS_AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID", "")

# ── Google Maps ──────────────────────────────────────────────
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

# ── Pub/Sub ──────────────────────────────────────────────────
PUBSUB_PROJECT_ID = os.getenv("PUBSUB_PROJECT_ID", GOOGLE_CLOUD_PROJECT)
PUBSUB_SUBSCRIPTION_NAME = os.getenv("PUBSUB_SUBSCRIPTION_NAME", "gmail-notifications-sub")
CRON_INTERVAL = int(os.getenv("CRON_INTERVAL", "60"))

# ── Calendar ─────────────────────────────────────────────────
CALENDAR_ID = os.getenv("CALENDAR_ID", "primary")
MEETING_DURATION_MINUTES = int(os.getenv("MEETING_DURATION_MINUTES", "30"))
BUSINESS_HOURS_START = int(os.getenv("BUSINESS_HOURS_START", "9"))
BUSINESS_HOURS_END = int(os.getenv("BUSINESS_HOURS_END", "17"))
SCHEDULING_DAYS_AHEAD = int(os.getenv("SCHEDULING_DAYS_AHEAD", "14"))
