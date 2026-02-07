"""
gmail_pubsub_listener/gmail_listener_service.py
Receives real-time Gmail notifications via Pub/Sub, fetches the email,
and forwards it to Lead Manager for processing.

Fallback: if Pub/Sub is unavailable, polls Gmail on a cron-like interval.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import signal
import sys
from datetime import datetime
from email.utils import parseaddr

import httpx
from dotenv import load_dotenv

from common.config import (
    GMAIL_LISTENER_PORT,
    LEAD_MANAGER_SERVICE_URL,
    PUBSUB_PROJECT_ID,
    PUBSUB_SUBSCRIPTION_NAME,
    SALES_EMAIL,
    CRON_INTERVAL,
    UI_CLIENT_URL,
)
from common.google_auth import get_gmail_service

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

# Track processed message IDs for idempotency
_processed_ids: set[str] = set()


# ── Gmail helpers ────────────────────────────────────────────

def _get_gmail_service():
    """Build Gmail API service using OAuth2."""
    return get_gmail_service()


def _extract_body(payload: dict) -> str:
    """Extract text body from Gmail message payload."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        body = _extract_body(part)
        if body:
            return body
    return ""


def _get_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def fetch_message(service, message_id: str) -> dict | None:
    """Fetch a full Gmail message by ID."""
    try:
        msg = service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()

        headers = msg.get("payload", {}).get("headers", [])
        sender_raw = _get_header(headers, "From")
        _, sender_email = parseaddr(sender_raw)

        return {
            "message_id": msg["id"],
            "thread_id": msg.get("threadId", ""),
            "sender": sender_email or sender_raw,
            "subject": _get_header(headers, "Subject"),
            "body": _extract_body(msg.get("payload", {}))[:3000],
            "received_at": _get_header(headers, "Date"),
        }
    except Exception as e:
        logger.error(f"Failed to fetch message {message_id}: {e}")
        return None


async def forward_to_lead_manager(email_data: dict):
    """Forward email data to Lead Manager's /process_single_email endpoint."""
    url = f"{LEAD_MANAGER_SERVICE_URL}/process_single_email"
    email_data["callback_url"] = f"{UI_CLIENT_URL}/agent_callback"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=email_data)
            resp.raise_for_status()
            result = resp.json()
            logger.info(f"Lead Manager response for {email_data.get('message_id')}: {result.get('status')}")
            return result
    except Exception as e:
        logger.error(f"Failed to forward to Lead Manager: {e}")
        return None


# ── Pub/Sub Listener ─────────────────────────────────────────

async def pubsub_listener():
    """Listen for Gmail push notifications via Google Cloud Pub/Sub."""
    try:
        from google.cloud import pubsub_v1

        subscriber = pubsub_v1.SubscriberClient()
        subscription_path = subscriber.subscription_path(
            PUBSUB_PROJECT_ID, PUBSUB_SUBSCRIPTION_NAME
        )

        gmail_service = _get_gmail_service()
        if not gmail_service:
            logger.error("Gmail service unavailable, falling back to polling")
            return False

        logger.info(f"Listening on {subscription_path}")

        def callback(message):
            try:
                data = json.loads(message.data.decode("utf-8"))
                history_id = data.get("historyId")
                logger.info(f"Pub/Sub notification: historyId={history_id}")

                # Fetch recent messages
                messages = gmail_service.users().messages().list(
                    userId="me", q="is:unread", maxResults=5
                ).execute().get("messages", [])

                for msg_stub in messages:
                    msg_id = msg_stub["id"]
                    if msg_id in _processed_ids:
                        continue

                    _processed_ids.add(msg_id)
                    email_data = fetch_message(gmail_service, msg_id)
                    if email_data:
                        # Run async forward in sync callback
                        asyncio.get_event_loop().create_task(
                            forward_to_lead_manager(email_data)
                        )

                message.ack()

            except Exception as e:
                logger.error(f"Pub/Sub callback error: {e}")
                message.nack()

        future = subscriber.subscribe(subscription_path, callback=callback)
        logger.info("Pub/Sub listener started successfully")

        try:
            future.result()
        except Exception as e:
            logger.error(f"Pub/Sub listener stopped: {e}")
            future.cancel()
            return False

    except ImportError:
        logger.warning("google-cloud-pubsub not available, using polling fallback")
        return False
    except Exception as e:
        logger.error(f"Pub/Sub setup failed: {e}, falling back to polling")
        return False

    return True


# ── Polling Fallback ─────────────────────────────────────────

async def polling_loop():
    """Poll Gmail for unread emails on a regular interval."""
    logger.info(f"Starting polling fallback (interval={CRON_INTERVAL}s)")

    gmail_service = _get_gmail_service()

    while True:
        try:
            if not gmail_service:
                gmail_service = _get_gmail_service()
                if not gmail_service:
                    logger.warning("Gmail service still unavailable, retrying...")
                    await asyncio.sleep(CRON_INTERVAL)
                    continue

            results = gmail_service.users().messages().list(
                userId="me", q="is:unread", maxResults=10
            ).execute()

            messages = results.get("messages", [])
            new_count = 0

            for msg_stub in messages:
                msg_id = msg_stub["id"]
                if msg_id in _processed_ids:
                    continue

                _processed_ids.add(msg_id)
                email_data = fetch_message(gmail_service, msg_id)
                if email_data:
                    await forward_to_lead_manager(email_data)
                    new_count += 1

            if new_count > 0:
                logger.info(f"Processed {new_count} new emails via polling")

        except Exception as e:
            logger.error(f"Polling error: {e}")

        await asyncio.sleep(CRON_INTERVAL)


# ── FastAPI app (for health checks) ─────────────────────────

from fastapi import FastAPI
import uvicorn

app = FastAPI(title="SalesShortcut Gmail Listener")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "gmail_listener",
        "processed_count": len(_processed_ids),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.on_event("startup")
async def startup():
    """Try Pub/Sub first, fall back to polling."""
    if PUBSUB_PROJECT_ID and PUBSUB_SUBSCRIPTION_NAME:
        # Try Pub/Sub in background task
        asyncio.create_task(_start_pubsub_or_poll())
    else:
        logger.info("Pub/Sub not configured, starting polling fallback")
        asyncio.create_task(polling_loop())


async def _start_pubsub_or_poll():
    """Attempt Pub/Sub, fall back to polling."""
    success = await pubsub_listener()
    if not success:
        logger.info("Pub/Sub failed, starting polling fallback")
        await polling_loop()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=GMAIL_LISTENER_PORT)
