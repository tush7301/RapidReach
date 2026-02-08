"""
sdr/tools/email_tool.py
Send HTML emails via Gmail using OAuth2 auth.
Supports attachments and tracking metadata.
"""

from __future__ import annotations

import base64
import json
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from common.config import SALES_EMAIL
from common.google_auth import get_gmail_service

logger = logging.getLogger(__name__)


async def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    business_name: str = "",
) -> str:
    """
    Send an HTML email from the sales account.

    Args:
        to_email: Recipient email address.
        subject: Email subject line.
        html_body: Full HTML body of the email.
        business_name: Name of the business (for logging).

    Returns:
        JSON string with send result.
    """
    if not SALES_EMAIL:
        return json.dumps({
            "success": False,
            "error": "SALES_EMAIL not configured in .env",
        })

    print(f"\n=== EMAIL SENDING START ===")
    print(f"To: {to_email}")
    print(f"Subject: {subject}")
    print(f"Business: {business_name}")
    print(f"HTML body length: {len(html_body)} chars")
    print("============================\n")

    service = get_gmail_service()
    if not service:
        return json.dumps({"success": False, "error": "Gmail OAuth2 not authorized. Run: PYTHONPATH=. python -m common.google_auth"})
    
    print(f"Preparing to send email to {to_email} for {business_name} with subject '{subject}'")
    try:
        message = MIMEMultipart("alternative")
        message["to"] = to_email
        message["from"] = SALES_EMAIL
        message["subject"] = subject

        # Plain text fallback
        plain = f"We have a proposal for {business_name}. Please view this email in an HTML-capable client."
        message.attach(MIMEText(plain, "plain"))
        message.attach(MIMEText(html_body, "html"))

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        result = service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()

        logger.info(f"Email sent to {to_email} for {business_name}: {result.get('id')}")
        return json.dumps({
            "success": True,
            "message_id": result.get("id", ""),
            "to": to_email,
            "subject": subject,
        })

    except Exception as e:
        logger.error(f"Email send failed for {to_email}: {e}")
        return json.dumps({"success": False, "error": str(e)})
