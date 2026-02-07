"""
lead_manager/tools/calendar_utils.py
Google Calendar API helpers — check availability, create meetings with Google Meet.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from common.config import (
    CALENDAR_ID,
    MEETING_DURATION_MINUTES,
    BUSINESS_HOURS_START,
    BUSINESS_HOURS_END,
    SCHEDULING_DAYS_AHEAD,
    SALES_EMAIL,
)
from common.google_auth import get_calendar_service

logger = logging.getLogger(__name__)


async def check_availability(preferred_date: str = "", preferred_time: str = "") -> str:
    """
    Check available meeting slots within business hours for the next N days.

    Args:
        preferred_date: Optional preferred date in YYYY-MM-DD format.
        preferred_time: Optional preferred time in HH:MM format.

    Returns:
        JSON with available time slots.
    """
    service = get_calendar_service()
    if not service:
        return json.dumps({"slots": [], "error": "Calendar OAuth2 not authorized. Run: PYTHONPATH=. python -m common.google_auth"})

    now = datetime.now(timezone.utc)
    end = now + timedelta(days=SCHEDULING_DAYS_AHEAD)

    try:
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        busy_times = []
        for event in events_result.get("items", []):
            start = event.get("start", {}).get("dateTime", "")
            end_time = event.get("end", {}).get("dateTime", "")
            if start and end_time:
                busy_times.append((start, end_time))

        # Generate available slots
        available_slots = []
        check_date = now.date() + timedelta(days=1)
        end_date = now.date() + timedelta(days=SCHEDULING_DAYS_AHEAD)

        while check_date <= end_date and len(available_slots) < 10:
            if check_date.weekday() < 5:  # Weekdays only
                for hour in range(BUSINESS_HOURS_START, BUSINESS_HOURS_END):
                    slot_start = datetime(
                        check_date.year, check_date.month, check_date.day,
                        hour, 0, tzinfo=timezone.utc
                    )
                    slot_end = slot_start + timedelta(minutes=MEETING_DURATION_MINUTES)

                    # Check if slot conflicts with busy times
                    is_free = True
                    for busy_start, busy_end in busy_times:
                        try:
                            bs = datetime.fromisoformat(busy_start)
                            be = datetime.fromisoformat(busy_end)
                            if not (slot_end <= bs or slot_start >= be):
                                is_free = False
                                break
                        except Exception:
                            pass

                    if is_free:
                        available_slots.append({
                            "start": slot_start.isoformat(),
                            "end": slot_end.isoformat(),
                            "date": check_date.isoformat(),
                            "time": f"{hour:02d}:00",
                        })

            check_date += timedelta(days=1)

        return json.dumps({"slots": available_slots[:10], "total_available": len(available_slots)})

    except Exception as e:
        logger.error(f"Availability check failed: {e}")
        return json.dumps({"slots": [], "error": str(e)})


async def create_meeting(
    attendee_email: str,
    start_time: str,
    business_name: str,
    summary: str = "",
    description: str = "",
) -> str:
    """
    Create a Google Calendar meeting with Google Meet link.

    Args:
        attendee_email: Email of the meeting attendee.
        start_time: ISO datetime for meeting start.
        business_name: Business name for the meeting title.
        summary: Meeting title/summary.
        description: Meeting description/agenda.

    Returns:
        JSON with meeting details including Google Meet link.
    """
    service = get_calendar_service()
    if not service:
        return json.dumps({"success": False, "error": "Calendar OAuth2 not authorized. Run: PYTHONPATH=. python -m common.google_auth"})

    if not summary:
        summary = f"Website Proposal Discussion — {business_name}"

    try:
        start_dt = datetime.fromisoformat(start_time)
        end_dt = start_dt + timedelta(minutes=MEETING_DURATION_MINUTES)

        event = {
            "summary": summary,
            "description": description or f"Discussion about website proposal for {business_name}.",
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": "UTC"},
            "attendees": [
                {"email": SALES_EMAIL},
                {"email": attendee_email},
            ],
            "conferenceData": {
                "createRequest": {
                    "requestId": str(uuid.uuid4()),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                },
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 60},
                    {"method": "popup", "minutes": 15},
                ],
            },
        }

        created = service.events().insert(
            calendarId=CALENDAR_ID,
            body=event,
            conferenceDataVersion=1,
            sendNotifications=True,
        ).execute()

        meet_link = ""
        conf = created.get("conferenceData", {})
        for ep in conf.get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                meet_link = ep.get("uri", "")
                break

        return json.dumps({
            "success": True,
            "event_id": created.get("id", ""),
            "html_link": created.get("htmlLink", ""),
            "google_meet_link": meet_link,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "attendee": attendee_email,
            "summary": summary,
        })

    except Exception as e:
        logger.error(f"Create meeting failed: {e}")
        return json.dumps({"success": False, "error": str(e)})
