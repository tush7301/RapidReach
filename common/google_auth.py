"""
common/google_auth.py
OAuth2 credential management for personal Gmail + Calendar access.

Usage:
    # One-time authorization (run from project root):
    PYTHONPATH=. python -m common.google_auth

    # In code:
    from common.google_auth import get_gmail_service, get_calendar_service
    service = get_gmail_service()
"""

from __future__ import annotations

import os
import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from common.config import OAUTH_CREDENTIALS_FILE, OAUTH_TOKEN_FILE

logger = logging.getLogger(__name__)

# All scopes the app needs — requested once during initial authorization
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]


def get_credentials() -> Credentials | None:
    """
    Load or refresh OAuth2 credentials.

    First run: opens a browser for user consent, saves token.json.
    Subsequent runs: loads token.json and auto-refreshes if expired.
    """
    creds = None

    # Load existing token
    token_path = Path(OAUTH_TOKEN_FILE)
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception as e:
            logger.warning(f"Failed to load token file: {e}")
            creds = None

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
            logger.info("OAuth2 token refreshed successfully")
        except Exception as e:
            logger.warning(f"Token refresh failed: {e}, re-authorization needed")
            creds = None

    # No valid creds — need interactive authorization
    if not creds or not creds.valid:
        creds_path = Path(OAUTH_CREDENTIALS_FILE)
        if not creds_path.exists():
            logger.error(
                f"OAuth credentials file not found at {OAUTH_CREDENTIALS_FILE}. "
                "Download it from GCP Console → APIs & Services → Credentials → "
                "OAuth 2.0 Client IDs → Download JSON"
            )
            return None

        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(creds_path), SCOPES
            )
            creds = flow.run_local_server(port=0)
            _save_token(creds)
            logger.info("OAuth2 authorization successful, token saved")
        except Exception as e:
            logger.error(f"OAuth2 authorization failed: {e}")
            return None

    return creds


def _save_token(creds: Credentials):
    """Save credentials to token file for reuse."""
    token_path = Path(OAUTH_TOKEN_FILE)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())


def get_gmail_service():
    """Build an authenticated Gmail API service."""
    creds = get_credentials()
    if not creds:
        logger.error("No valid OAuth2 credentials for Gmail")
        return None
    return build("gmail", "v1", credentials=creds)


def get_calendar_service():
    """Build an authenticated Google Calendar API service."""
    creds = get_credentials()
    if not creds:
        logger.error("No valid OAuth2 credentials for Calendar")
        return None
    return build("calendar", "v3", credentials=creds)


# ── CLI: Run this module to authorize ────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=" * 60)
    print("SalesShortcut — Google OAuth2 Authorization")
    print("=" * 60)
    print()
    print(f"Credentials file: {OAUTH_CREDENTIALS_FILE}")
    print(f"Token will be saved to: {OAUTH_TOKEN_FILE}")
    print()
    print("A browser window will open for you to sign in with your")
    print("Gmail account and grant permissions.")
    print()

    creds = get_credentials()
    if creds and creds.valid:
        print()
        print("✅ Authorization successful!")
        print(f"   Token saved to: {OAUTH_TOKEN_FILE}")
        print()
        print("You can now start all services. The token will auto-refresh.")
    else:
        print()
        print("❌ Authorization failed. Check the error messages above.")
