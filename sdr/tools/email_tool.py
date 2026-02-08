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
from email.mime.application import MIMEApplication
from typing import Optional, Dict, Any

from common.config import SALES_EMAIL
from common.google_auth import get_gmail_service

logger = logging.getLogger(__name__)


async def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    business_name: str = "",
    attachment_data: Optional[Dict[str, Any]] = None,
    calendar_ics: Optional[str] = None,
) -> str:
    """
    Send an HTML email from the sales account.

    Args:
        to_email: Recipient email address.
        subject: Email subject line.
        html_body: Full HTML body of the email.
        business_name: Name of the business (for logging).
        attachment_data: Optional dict with 'filename', 'content_b64', and 'mimetype'.
        calendar_ics: Optional iCalendar (.ics) string to attach as a calendar invite.

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
    if attachment_data:
        print(f"Attachment: {attachment_data.get('filename', 'unnamed')}")
    print("============================\n")

    service = get_gmail_service()
    if not service:
        return json.dumps({"success": False, "error": "Gmail OAuth2 not authorized. Run: PYTHONPATH=. python -m common.google_auth"})
    
    print(f"Preparing to send email to {to_email} for {business_name} with subject '{subject}'")
    try:
        message = MIMEMultipart("mixed")
        message["to"] = to_email
        message["from"] = f"RapidReach Team <{SALES_EMAIL}>"
        message["subject"] = subject

        # Create HTML/plain text part
        msg_body = MIMEMultipart("alternative")
        
        # Plain text fallback
        plain = f"We have a proposal for {business_name}. Please view this email in an HTML-capable client."
        msg_body.attach(MIMEText(plain, "plain"))
        msg_body.attach(MIMEText(html_body, "html"))
        
        message.attach(msg_body)

        # Add attachment if provided
        if attachment_data and attachment_data.get('content_b64'):
            try:
                # Decode base64 attachment
                file_content = base64.b64decode(attachment_data['content_b64'])
                filename = attachment_data.get('filename', 'attachment.pptx')
                mimetype = attachment_data.get('mimetype', 'application/vnd.openxmlformats-officedocument.presentationml.presentation')
                
                attachment = MIMEApplication(file_content, _subtype=mimetype.split('/')[1] if '/' in mimetype else 'octet-stream')
                attachment.add_header('Content-Disposition', f'attachment; filename="{filename}"')
                message.attach(attachment)
                print(f"✅ Attached file: {filename}")
            except Exception as e:
                print(f"⚠️ Attachment failed: {e}")
                # Continue without attachment

        # Add calendar invite (.ics) if provided
        if calendar_ics:
            try:
                ics_attachment = MIMEText(calendar_ics, 'calendar', 'utf-8')
                ics_attachment.add_header('Content-Disposition', 'attachment; filename="meeting.ics"')
                message.attach(ics_attachment)
                print("📅 Attached calendar invite (meeting.ics)")
            except Exception as e:
                print(f"⚠️ Calendar attachment failed: {e}")

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
            "attachment_included": bool(attachment_data),
            "calendar_invite_included": bool(calendar_ics),
        })

    except Exception as e:
        logger.error(f"Email send failed for {to_email}: {e}")
        return json.dumps({"success": False, "error": str(e)})
