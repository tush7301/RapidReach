"""
sdr/tools/phone_call.py
ElevenLabs Conversational AI phone call wrapper.
Uses batch_calls API for outbound calls, polls for completion, fetches transcript.
Includes cooldown to prevent repeated calls to the same lead.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime

from common.config import ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID, ELEVENLABS_PHONE_NUMBER_ID

logger = logging.getLogger(__name__)

# Cooldown: no repeat calls to the same number within N seconds
CALL_COOLDOWN_SECONDS = 3600  # 1 hour
_recent_calls: dict[str, float] = {}

# Max time to wait for a call to complete (seconds)
CALL_TIMEOUT = 300  # 5 minutes
POLL_INTERVAL = 5   # check every 5 seconds


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
    print(f"Initiating call to {business_name} at {phone_number}")
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
    print("Placing call")
    try:
        from elevenlabs.client import ElevenLabs
        from elevenlabs.types import OutboundCallRecipient
        from elevenlabs.types.conversation_initiation_client_data_request_input import (
            ConversationInitiationClientDataRequestInput,
        )

        el_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        print("ElevenLabs client initialized, business_name:", business_name, "phone:", validated, "context:", context)
        # Build recipient with dynamic variables for the agent
        recipient = OutboundCallRecipient(
            phone_number=validated,
            conversation_initiation_client_data=ConversationInitiationClientDataRequestInput(
                dynamic_variables={
                    "business_name": business_name,
                    "context": context[:500],
                    "proposal": proposal_summary[:500],
                },
            ),
        )

        # Create a batch call (works for single calls too)
        batch = el_client.conversational_ai.batch_calls.create(
            call_name=f"SDR Call — {business_name}",
            agent_id=ELEVENLABS_AGENT_ID,
            agent_phone_number_id=ELEVENLABS_PHONE_NUMBER_ID,
            recipients=[recipient],
        )

        batch_id = batch.id
        logger.info(f"Batch call created: {batch_id} for {business_name}")

        _recent_calls[validated] = time.time()

        # Poll until the call finishes or times out
        transcript = ""
        conversation_id = ""
        call_status = "initiated"
        elapsed = 0

        while elapsed < CALL_TIMEOUT:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

            try:
                details = el_client.conversational_ai.batch_calls.get(batch_id=batch_id)
                # Check if all calls are finished
                if details.total_calls_finished >= details.total_calls_dispatched and details.total_calls_dispatched > 0:
                    call_status = "completed"

                    # Get the conversation ID from the recipient
                    if details.recipients:
                        r = details.recipients[0]
                        conversation_id = getattr(r, "conversation_id", "") or ""
                        call_status = getattr(r, "status", "completed") or "completed"

                    break

                status_str = getattr(details, "status", "")
                if status_str in ("failed", "cancelled"):
                    call_status = status_str
                    break

            except Exception as poll_err:
                logger.warning(f"Polling error: {poll_err}")

        # Fetch transcript if we have a conversation ID
        if conversation_id:
            try:
                convo = el_client.conversational_ai.conversations.get(
                    conversation_id=conversation_id
                )
                # Build transcript from the conversation
                if hasattr(convo, "transcript") and convo.transcript:
                    lines = []
                    for turn in convo.transcript:
                        role = getattr(turn, "role", "unknown")
                        text = getattr(turn, "message", "") or getattr(turn, "text", "")
                        if text:
                            lines.append(f"{role}: {text}")
                    transcript = "\n".join(lines)

                if not transcript and hasattr(convo, "analysis") and convo.analysis:
                    transcript = getattr(convo.analysis, "transcript_summary", "") or ""

            except Exception as t_err:
                logger.warning(f"Failed to fetch transcript: {t_err}")

        
        print(json.dumps({
            "success": True,
            "phone_number": validated,
            "business_name": business_name,
            "transcript": transcript or "(call completed, transcript unavailable)",
            "conversation_id": conversation_id,
            "batch_id": batch_id,
            "status": call_status,
            "called_at": datetime.utcnow().isoformat(),
        }))

        return json.dumps({
            "success": True,
            "phone_number": validated,
            "business_name": business_name,
            "transcript": transcript or "(call completed, transcript unavailable)",
            "conversation_id": conversation_id,
            "batch_id": batch_id,
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
