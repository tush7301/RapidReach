"""
lead_manager/tools/check_email.py
Gmail API access — fetch unread emails from the sales inbox.
Uses OAuth2 for personal Gmail access.
"""

from __future__ import annotations

import base64
import json
import logging
from email.utils import parseaddr

from common.config import SALES_EMAIL
from common.google_auth import get_gmail_service

logger = logging.getLogger(__name__)


def _extract_body(payload: dict) -> str:
    """Extract plain text body from Gmail message payload."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    parts = payload.get("parts", [])
    for part in parts:
        body = _extract_body(part)
        if body:
            return body
    return ""


def _get_header(headers: list[dict], name: str) -> str:
    """Get a header value by name."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


async def fetch_unread_emails(max_emails: int = 10) -> str:
    """
    Fetch unread emails from the sales inbox.

    Args:
        max_emails: Maximum number of emails to fetch.

    Returns:
        JSON string with list of email records.
    """
    if not SALES_EMAIL:
        return json.dumps({"emails": [], "error": "SALES_EMAIL not configured in .env"})

    service = get_gmail_service()
    if not service:
        return json.dumps({"emails": [], "error": "Gmail OAuth2 not authorized. Run: PYTHONPATH=. python -m common.google_auth"})

    try:
        results = service.users().messages().list(
            userId="me",
            q="is:unread",
            maxResults=max_emails,
        ).execute()

        messages = results.get("messages", [])
        emails = []

        for msg_stub in messages:
            msg = service.users().messages().get(
                userId="me", id=msg_stub["id"], format="full"
            ).execute()

            headers = msg.get("payload", {}).get("headers", [])
            sender_raw = _get_header(headers, "From")
            _, sender_email = parseaddr(sender_raw)

            email_record = {
                "message_id": msg["id"],
                "thread_id": msg.get("threadId", ""),
                "sender": sender_email or sender_raw,
                "subject": _get_header(headers, "Subject"),
                "body": _extract_body(msg.get("payload", {}))[:3000],
                "received_at": _get_header(headers, "Date"),
                "is_read": False,
            }
            emails.append(email_record)

        return json.dumps({"emails": emails, "total": len(emails)})

    except Exception as e:
        logger.error(f"Fetch emails failed: {e}")
        return json.dumps({"emails": [], "error": str(e)})


async def mark_email_as_read(message_id: str) -> str:
    """
    Mark an email as read in Gmail.

    Args:
        message_id: Gmail message ID.

    Returns:
        JSON result.
    """
    service = get_gmail_service()
    if not service:
        return json.dumps({"success": False, "error": "Gmail OAuth2 not authorized"})

    try:
        service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()
        return json.dumps({"success": True, "message_id": message_id})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})
