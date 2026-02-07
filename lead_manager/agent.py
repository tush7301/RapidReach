"""
lead_manager/agent.py
Lead Manager Agent — FastAPI service + Dedalus DedalusRunner orchestration.

Architecture:
  Coordinator delegates to specialist tools:
    1. fetch_unread_emails — pulls emails from Gmail
    2. check_if_known_lead — looks up sender in BigQuery
    3. analyze_email — LLM analysis (meeting request? hot lead?)
    4. check_availability — finds open calendar slots
    5. create_meeting — books meeting with Google Meet link
    6. mark_email_as_read — marks processed emails
  Callbacks stream events to UI Client.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import FastAPI
from dedalus_labs import AsyncDedalus, DedalusRunner
from dotenv import load_dotenv

from common.config import DEFAULT_MODEL, CLASSIFIER_MODEL, UI_CLIENT_URL
from common.models import (
    AgentCallback,
    AgentType,
    EmailAnalysis,
    Meeting,
    ProcessEmailsRequest,
)
from lead_manager.tools.check_email import fetch_unread_emails, mark_email_as_read
from lead_manager.tools.calendar_utils import check_availability, create_meeting
from lead_manager.tools.bigquery_utils import (
    check_if_known_lead,
    save_meeting,
    update_lead_status,
)

load_dotenv()
logger = logging.getLogger(__name__)

# In-memory stores
processed_emails: dict[str, dict] = {}
scheduled_meetings: list[Meeting] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Lead Manager service starting")
    yield
    logger.info("Lead Manager service shutting down")


app = FastAPI(title="SalesShortcut Lead Manager", lifespan=lifespan)


# ── Helper: send callback to UI ─────────────────────────────

async def notify_ui(callback_url: str, payload: AgentCallback):
    url = callback_url or f"{UI_CLIENT_URL}/agent_callback"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json=payload.model_dump())
    except Exception as e:
        logger.warning(f"UI callback failed: {e}")


# ── Specialist: email analysis (agent-as-tool) ──────────────

async def analyze_email(
    sender: str,
    subject: str,
    body: str,
    is_known_lead: bool = False,
    lead_info: str = "",
) -> str:
    """
    Analyze an email to determine if it's a meeting request, hot lead signal,
    or routine message. Returns structured analysis.

    Args:
        sender: Sender email address.
        subject: Email subject line.
        body: Email body text.
        is_known_lead: Whether sender is a known lead.
        lead_info: JSON string of lead info if known.

    Returns:
        JSON analysis with meeting request detection, confidence, and recommendations.
    """
    client = AsyncDedalus()
    runner = DedalusRunner(client)

    result = await runner.run(
        input=f"""Analyze this inbound email for sales-relevant signals.

FROM: {sender}
SUBJECT: {subject}
BODY:
{body[:2000]}

KNOWN LEAD: {is_known_lead}
LEAD INFO: {lead_info}

Determine:
1. Is this a meeting request? (explicit like "let's schedule a call" or implicit like "I'd love to learn more")
2. How confident are you? (0.0 to 1.0)
3. Is this a hot lead? (high interest signals)
4. What's the suggested response?
5. If they mentioned a preferred time, extract it.
6. Brief summary.

Return a JSON object:
{{
  "is_from_known_lead": {str(is_known_lead).lower()},
  "lead_place_id": "",
  "business_name": "",
  "is_meeting_request": true/false,
  "meeting_confidence": 0.0-1.0,
  "is_hot_lead": true/false,
  "suggested_response": "...",
  "preferred_meeting_time": "..." or null,
  "summary": "..."
}}

Return ONLY the JSON.""",
        model=CLASSIFIER_MODEL,
        response_format=EmailAnalysis,
        max_steps=2,
    )

    output = result.final_output
    if hasattr(output, "model_dump"):
        return json.dumps(output.model_dump())
    return output if isinstance(output, str) else json.dumps(output)


# ── API Endpoints ────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "lead_manager", "timestamp": datetime.utcnow().isoformat()}


@app.post("/process_emails")
async def process_emails_endpoint(req: ProcessEmailsRequest):
    """
    Scan the inbox and process unread emails.
    For each email: check if known lead → analyze → schedule meeting if needed.
    """
    callback_url = req.callback_url

    await notify_ui(callback_url, AgentCallback(
        agent_type=AgentType.LEAD_MANAGER,
        event="processing_started",
        message="Scanning inbox for new emails",
    ))

    try:
        client = AsyncDedalus()
        runner = DedalusRunner(client)

        instructions = f"""You are a Lead Manager. Your job is to process incoming emails
from the sales inbox and take appropriate action.

Steps:
1. Call fetch_emails to get unread emails (max {req.max_emails}).
2. For each email:
   a. Call check_lead to see if the sender is a known lead.
   b. Call analyze_email with the email content and lead info.
   c. If the analysis says it's a meeting request with confidence > 0.6:
      - Call check_calendar to find available slots.
      - Call schedule_meeting with the first available slot and attendee email.
      - Call mark_read to mark the email as processed.
   d. If it's a hot lead but not a meeting request:
      - Note it for follow-up.
      - Call mark_read.
   e. Otherwise, just call mark_read.
3. Provide a summary of all actions taken.

Be thorough and handle each email."""

        # Build tool functions
        async def fetch_emails(max_count: int = 10) -> str:
            """Fetch unread emails from the sales inbox."""
            return await fetch_unread_emails(max_emails=max_count)

        async def check_lead(sender_email: str) -> str:
            """Check if an email sender is a known lead."""
            return await check_if_known_lead(sender_email)

        async def check_calendar(preferred_date: str = "", preferred_time: str = "") -> str:
            """Check available meeting slots."""
            return await check_availability(preferred_date, preferred_time)

        async def schedule_meeting(
            attendee_email: str,
            start_time: str,
            business_name: str = "Prospect",
            description: str = "",
        ) -> str:
            """Create a calendar meeting with Google Meet link."""
            result_json = await create_meeting(
                attendee_email=attendee_email,
                start_time=start_time,
                business_name=business_name,
                description=description,
            )
            # Parse and store
            try:
                result_data = json.loads(result_json)
                if result_data.get("success"):
                    meeting = Meeting(
                        meeting_id=result_data.get("event_id", ""),
                        business_name=business_name,
                        attendee_email=attendee_email,
                        start_time=result_data.get("start", ""),
                        end_time=result_data.get("end", ""),
                        google_meet_link=result_data.get("google_meet_link", ""),
                        calendar_event_id=result_data.get("event_id", ""),
                    )
                    scheduled_meetings.append(meeting)

                    # Save to BQ
                    save_meeting(meeting.model_dump())

                    # Notify UI
                    import asyncio
                    asyncio.create_task(notify_ui(callback_url, AgentCallback(
                        agent_type=AgentType.CALENDAR,
                        event="meeting_scheduled",
                        business_name=business_name,
                        message=f"Meeting scheduled with {attendee_email}",
                        data=result_data,
                    )))
            except Exception:
                pass
            return result_json

        async def mark_read(message_id: str) -> str:
            """Mark an email as read."""
            return await mark_email_as_read(message_id)

        result = await runner.run(
            input=instructions,
            model=DEFAULT_MODEL,
            tools=[
                fetch_emails,
                check_lead,
                analyze_email,
                check_calendar,
                schedule_meeting,
                mark_read,
            ],
            max_steps=20,
        )

        await notify_ui(callback_url, AgentCallback(
            agent_type=AgentType.LEAD_MANAGER,
            event="processing_completed",
            message="Email processing complete",
            data={"summary": result.final_output[:1000] if result.final_output else ""},
        ))

        return {
            "status": "success",
            "summary": result.final_output,
            "meetings_scheduled": len(scheduled_meetings),
        }

    except Exception as e:
        logger.error(f"Email processing failed: {e}")
        await notify_ui(callback_url, AgentCallback(
            agent_type=AgentType.LEAD_MANAGER,
            event="error",
            message=f"Processing failed: {str(e)}",
        ))
        return {"status": "error", "message": str(e)}


@app.post("/process_single_email")
async def process_single_email(email_data: dict):
    """
    Process a single email forwarded by the Gmail Pub/Sub Listener.
    """
    callback_url = email_data.get("callback_url", "")
    sender = email_data.get("sender", "")
    subject = email_data.get("subject", "")
    body = email_data.get("body", "")
    message_id = email_data.get("message_id", "")

    if message_id in processed_emails:
        return {"status": "already_processed", "message_id": message_id}

    try:
        # Check if known lead
        lead_result = await check_if_known_lead(sender)
        lead_data = json.loads(lead_result)
        is_known = lead_data.get("is_known", False)

        # Analyze
        analysis_result = await analyze_email(
            sender=sender,
            subject=subject,
            body=body,
            is_known_lead=is_known,
            lead_info=lead_result if is_known else "",
        )

        analysis = json.loads(analysis_result) if isinstance(analysis_result, str) else analysis_result

        result_data = {
            "message_id": message_id,
            "sender": sender,
            "analysis": analysis,
            "action_taken": "none",
        }

        # If meeting request with high confidence
        if analysis.get("is_meeting_request") and analysis.get("meeting_confidence", 0) > 0.6:
            avail = await check_availability(
                preferred_date=analysis.get("preferred_meeting_time", "") or "",
            )
            slots = json.loads(avail).get("slots", [])

            if slots:
                meeting_result = await create_meeting(
                    attendee_email=sender,
                    start_time=slots[0]["start"],
                    business_name=analysis.get("business_name", "Prospect"),
                )
                result_data["action_taken"] = "meeting_scheduled"
                result_data["meeting"] = json.loads(meeting_result)

                await notify_ui(callback_url, AgentCallback(
                    agent_type=AgentType.CALENDAR,
                    event="meeting_scheduled",
                    business_name=analysis.get("business_name", ""),
                    message=f"Meeting auto-scheduled with {sender}",
                    data=result_data["meeting"],
                ))

        elif analysis.get("is_hot_lead"):
            result_data["action_taken"] = "hot_lead_flagged"
            if is_known and lead_data.get("place_id"):
                update_lead_status(lead_data["place_id"], "hot_lead")

            await notify_ui(callback_url, AgentCallback(
                agent_type=AgentType.LEAD_MANAGER,
                event="hot_lead_detected",
                business_name=analysis.get("business_name", ""),
                message=f"Hot lead detected: {sender}",
                data=analysis,
            ))

        # Mark as read
        if message_id:
            await mark_email_as_read(message_id)

        processed_emails[message_id] = result_data
        return {"status": "success", **result_data}

    except Exception as e:
        logger.error(f"Single email processing failed: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/meetings")
async def get_meetings():
    return {"meetings": [m.model_dump() for m in scheduled_meetings]}
