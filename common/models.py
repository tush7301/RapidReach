"""
common/models.py
Shared Pydantic models used across all services.
Single source of truth for Lead, Meeting, SDRResult, EmailRecord, and callback payloads.
"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────

class LeadStatus(str, Enum):
    NEW = "new"
    CONTACTED = "contacted"
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"
    MEETING_SCHEDULED = "meeting_scheduled"
    HOT_LEAD = "hot_lead"
    CLOSED = "closed"


class CallOutcome(str, Enum):
    INTERESTED = "interested"
    AGREED_TO_EMAIL = "agreed_to_email"
    NOT_INTERESTED = "not_interested"
    NO_ANSWER = "no_answer"
    ISSUE = "issue_appeared"
    OTHER = "other"


class AgentType(str, Enum):
    LEAD_FINDER = "lead_finder"
    SDR = "sdr"
    LEAD_MANAGER = "lead_manager"
    GMAIL_LISTENER = "gmail_listener"
    CALENDAR = "calendar"
    DECK_GENERATOR = "deck_generator"


# ── Core Data Models ─────────────────────────────────────────

class Lead(BaseModel):
    """A business lead discovered by Lead Finder or enriched by SDR."""
    place_id: str = ""
    business_name: str
    address: str = ""
    city: str = ""
    phone: str = ""
    email: str = ""
    website: Optional[str] = None
    rating: Optional[float] = None
    total_ratings: Optional[int] = None
    business_type: str = ""
    has_website: bool = False
    lead_status: LeadStatus = LeadStatus.NEW
    discovered_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    notes: str = ""


class Meeting(BaseModel):
    """A scheduled meeting with a lead."""
    meeting_id: str = ""
    lead_place_id: str = ""
    business_name: str = ""
    attendee_email: str = ""
    start_time: str = ""
    end_time: str = ""
    google_meet_link: str = ""
    calendar_event_id: str = ""
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    notes: str = ""


class SDRResult(BaseModel):
    """Result of an SDR outreach session."""
    session_id: str = ""
    lead_place_id: str = ""
    business_name: str = ""
    research_summary: str = ""
    proposal_summary: str = ""
    call_transcript: str = ""
    call_outcome: CallOutcome = CallOutcome.OTHER
    email_sent: bool = False
    email_subject: str = ""
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class EmailRecord(BaseModel):
    """An email fetched from Gmail."""
    message_id: str = ""
    thread_id: str = ""
    sender: str = ""
    subject: str = ""
    body: str = ""
    received_at: str = ""
    is_read: bool = False


class EmailAnalysis(BaseModel):
    """LLM analysis of an inbound email."""
    is_from_known_lead: bool = False
    lead_place_id: str = ""
    business_name: str = ""
    is_meeting_request: bool = False
    meeting_confidence: float = 0.0
    is_hot_lead: bool = False
    suggested_response: str = ""
    preferred_meeting_time: Optional[str] = None
    summary: str = ""


class ConversationClassification(BaseModel):
    """Classification of a phone call outcome."""
    outcome: CallOutcome
    confidence: float = 0.0
    key_points: list[str] = []
    next_action: str = ""
    summary: str = ""


class ProposalDraft(BaseModel):
    """A website proposal draft."""
    business_name: str
    value_proposition: str = ""
    proposed_sections: list[str] = []
    pricing_notes: str = ""
    full_draft: str = ""
    fact_check_notes: str = ""


# ── Callback / Event Payloads ────────────────────────────────

class AgentCallback(BaseModel):
    """Payload sent by agents to the UI via /agent_callback."""
    agent_type: AgentType
    event: str  # e.g. "lead_found", "call_completed", "meeting_scheduled"
    business_id: str = ""
    business_name: str = ""
    status: str = ""
    message: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    data: dict[str, Any] = {}


# ── Request / Response Models ────────────────────────────────

class FindLeadsRequest(BaseModel):
    city: str
    radius_km: int = 10
    max_results: int = 20
    business_types: list[str] = []
    exclude_chains: bool = True
    min_rating: float = 0.0
    callback_url: str = ""


class SDRRequest(BaseModel):
    business_name: str
    phone: str = ""
    email: str = ""
    address: str = ""
    city: str = ""
    place_id: str = ""
    lead_context: str = ""
    callback_url: str = ""
    skip_call: bool = False
    deck_template: str = "professional"


class ProcessEmailsRequest(BaseModel):
    callback_url: str = ""
    max_emails: int = 10
