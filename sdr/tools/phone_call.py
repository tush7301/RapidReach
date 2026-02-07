"""
sdr/tools/phone_call.py
ElevenLabs Conversational AI phone call wrapper.
Validates phone numbers, initiates calls, captures transcripts.
Includes cooldown to prevent repeated calls to the same lead.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime

from common.config import ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID

logger = logging.getLogger(__name__)

# Cooldown: no repeat calls to the same number within N seconds
CALL_COOLDOWN_SECONDS = 3600  # 1 hour
_recent_calls: dict[str, float] = {}


def _validate_phone(phone: str) -> str | None:
    """Basic phone validation — strip non-digits, check length."""
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) < 10:
        return None
    if not digits.startswith("1") and len(digits) == 10:
        digits = "1" + digits
    return f"+{digits}"


async def make_phone_call(
    phone_number: str,
    business_name: str,
    context: str = "",
    proposal_summary: str = "",
) -> str:
    """
    Place an AI-powered phone call to a business using ElevenLabs.

    Args:
        phone_number: The business phone number to call.
        business_name: Name of the business being called.
        context: Background research and context about the business.
        proposal_summary: Summary of the proposal to present.

    Returns:
        JSON string with call result including transcript and outcome.
    """
    if not ELEVENLABS_API_KEY or not ELEVENLABS_AGENT_ID:
        return json.dumps({
            "success": False,
            "error": "ElevenLabs API key or Agent ID not configured",
            "transcript": "",
            "outcome": "issue_appeared",
        })

    validated = _validate_phone(phone_number)
    if not validated:
        return json.dumps({
            "success": False,
            "error": f"Invalid phone number: {phone_number}",
            "transcript": "",
            "outcome": "issue_appeared",
        })

    # Cooldown check
    last_call = _recent_calls.get(validated, 0)
    if time.time() - last_call < CALL_COOLDOWN_SECONDS:
        mins_ago = int((time.time() - last_call) / 60)
        return json.dumps({
            "success": False,
            "error": f"Called {validated} {mins_ago} min ago. Cooldown active.",
            "transcript": "",
            "outcome": "other",
        })

    try:
        from elevenlabs.client import ElevenLabs

        el_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

        # Initiate conversational call
        # NOTE: The exact API depends on your ElevenLabs plan / agent setup.
        # This uses the Conversational AI outbound call API.
        call_result = el_client.conversational_ai.create_call(
            agent_id=ELEVENLABS_AGENT_ID,
            phone_number=validated,
            first_message=f"Hi, am I speaking with someone from {business_name}?",
            variables={
                "business_name": business_name,
                "context": context[:500],
                "proposal": proposal_summary[:500],
            },
        )

        _recent_calls[validated] = time.time()

        transcript = getattr(call_result, "transcript", "")
        call_duration = getattr(call_result, "duration_seconds", 0)
        call_status = getattr(call_result, "status", "completed")

        return json.dumps({
            "success": True,
            "phone_number": validated,
            "business_name": business_name,
            "transcript": transcript,
            "duration_seconds": call_duration,
            "status": call_status,
            "called_at": datetime.utcnow().isoformat(),
        })

    except Exception as e:
        logger.error(f"Phone call failed for {business_name}: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "transcript": "",
            "outcome": "issue_appeared",
        })
