"""
sdr/agent.py
SDR Agent — FastAPI service + Dedalus DedalusRunner orchestration.

Architecture (Agent-as-Tool pattern):
  Coordinator (cheap model) delegates to specialist tools:
    1. research_business — deep web research via Brave Search MCP
    2. draft_proposal — writes a tailored website proposal (strong model)
    3. fact_check_proposal — validates/refines the draft (generator-critic)
    4. call_business — AI phone call via ElevenLabs
    5. classify_conversation — LLM classification of call outcome
    6. send_outreach_email — HTML email via Gmail service account
    7. save_session — persist results to BigQuery
  Callbacks stream progress to the UI Client.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import FastAPI
from dedalus_labs import AsyncDedalus, DedalusRunner
from dotenv import load_dotenv

from common.config import (
    DEFAULT_MODEL,
    RESEARCH_MODEL,
    DRAFT_MODEL,
    CLASSIFIER_MODEL,
    UI_CLIENT_URL,
)
from common.models import (
    AgentCallback,
    AgentType,
    CallOutcome,
    ConversationClassification,
    ProposalDraft,
    SDRRequest,
    SDRResult,
)
from sdr.tools.phone_call import make_phone_call
from sdr.tools.email_tool import send_email
from sdr.tools.bigquery_utils import save_sdr_session, update_lead_status

load_dotenv()
logger = logging.getLogger(__name__)

# In-memory session store
sdr_sessions: dict[str, SDRResult] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("SDR Agent service starting")
    yield
    logger.info("SDR Agent service shutting down")


app = FastAPI(title="SalesShortcut SDR Agent", lifespan=lifespan)


# ── Helper: send callback to UI ─────────────────────────────

async def notify_ui(callback_url: str, payload: AgentCallback):
    url = callback_url or f"{UI_CLIENT_URL}/agent_callback"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json=payload.model_dump())
    except Exception as e:
        logger.warning(f"UI callback failed: {e}")


# ── Specialist Tools (Agent-as-Tool pattern) ─────────────────

async def research_business(business_name: str, city: str, address: str = "") -> str:
    """
    Deep research on a business using web search.
    Examines competitors, reviews, web presence gaps, and market opportunities.
    Returns a detailed research summary.
    """
    client = AsyncDedalus()
    runner = DedalusRunner(client)

    result = await runner.run(
        input=f"""Research this business thoroughly:
Business: {business_name}
City: {city}
Address: {address}

Find:
1. Their online presence (or lack thereof)
2. Competitor businesses nearby that DO have websites
3. Customer reviews and reputation
4. Market gaps and opportunities
5. What type of website would benefit them most

Provide a detailed research report.""",
        model=RESEARCH_MODEL,
        mcp_servers=["windsor/brave-search-mcp"],
        max_steps=5,
    )
    return result.final_output


async def draft_proposal(business_name: str, research_summary: str) -> str:
    """
    Write a tailored website proposal for a business based on research.
    Returns a structured proposal with value proposition, sections, and pricing.
    """
    client = AsyncDedalus()
    runner = DedalusRunner(client)

    result = await runner.run(
        input=f"""Write a compelling, tailored website proposal for {business_name}.

Research findings:
{research_summary}

Create a proposal with:
1. **Value Proposition**: Why they need a website (use specific data from research)
2. **Proposed Website Sections**: Home, About, Services, Contact, etc. tailored to their business
3. **Key Features**: Online booking, menu display, gallery, testimonials, etc.
4. **Expected Benefits**: More customers, credibility, 24/7 visibility
5. **Pricing Notes**: Competitive pricing suggestions
6. **Timeline**: Estimated delivery

Make it persuasive, specific to their business, and professional.
Return the full proposal text.""",
        model=DRAFT_MODEL,
        max_steps=3,
    )
    return result.final_output


async def fact_check_proposal(proposal_text: str, business_name: str, research_summary: str) -> str:
    """
    Validate and refine a website proposal for accuracy and persuasiveness.
    Acts as a critic — checks claims, improves weak points, ensures professionalism.
    Returns the refined proposal.
    """
    client = AsyncDedalus()
    runner = DedalusRunner(client)

    result = await runner.run(
        input=f"""You are a proposal reviewer and fact-checker. Review this website proposal for {business_name}:

PROPOSAL:
{proposal_text}

ORIGINAL RESEARCH:
{research_summary}

Check for:
1. Accuracy — are all claims supported by the research?
2. Persuasiveness — is the value proposition compelling?
3. Professionalism — tone, grammar, formatting
4. Missing points — anything important left out?
5. Pricing — is it realistic for a small business?

Return the improved, fact-checked version of the full proposal.""",
        model=CLASSIFIER_MODEL,
        max_steps=3,
    )
    return result.final_output


async def classify_call_outcome(transcript: str, business_name: str) -> str:
    """
    Classify the outcome of a phone call based on its transcript.
    Returns JSON with outcome, confidence, key points, and recommended next action.
    """
    client = AsyncDedalus()
    runner = DedalusRunner(client)

    result = await runner.run(
        input=f"""Classify this phone call transcript with {business_name}.

TRANSCRIPT:
{transcript}

Classify the outcome as one of:
- "interested": They showed clear interest in a website
- "agreed_to_email": They want more info via email
- "not_interested": They declined
- "no_answer": No one picked up or voicemail
- "issue_appeared": Technical issue or hostile response
- "other": None of the above

Return a JSON object with:
{{
  "outcome": "<one of the above>",
  "confidence": <0.0 to 1.0>,
  "key_points": ["<point1>", "<point2>"],
  "next_action": "<recommended next step>",
  "summary": "<one-sentence summary>"
}}

Return ONLY the JSON, no other text.""",
        model=CLASSIFIER_MODEL,
        response_format=ConversationClassification,
        max_steps=2,
    )
    return result.final_output if isinstance(result.final_output, str) else json.dumps(result.final_output)


# ── API Endpoints ────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "sdr", "timestamp": datetime.utcnow().isoformat()}


@app.post("/run_sdr")
async def run_sdr_endpoint(req: SDRRequest):
    """
    Execute the full SDR pipeline for a business lead.
    Research → Proposal → Call → Classify → Email (if interested) → Save.
    """
    session_id = str(uuid.uuid4())
    callback_url = req.callback_url

    await notify_ui(callback_url, AgentCallback(
        agent_type=AgentType.SDR,
        event="sdr_started",
        business_name=req.business_name,
        business_id=req.place_id,
        message=f"Starting SDR outreach for {req.business_name}",
    ))

    try:
        client = AsyncDedalus()
        runner = DedalusRunner(client)

        # Build the coordinator instructions
        instructions = f"""You are an AI Sales Development Representative (SDR). Your mission is to
reach out to {req.business_name} and convince them they need a professional website.

Business Info:
- Name: {req.business_name}
- Phone: {req.phone}
- Email: {req.email}
- Address: {req.address}
- City: {req.city}
- Context: {req.lead_context}

Execute this pipeline IN ORDER:

1. RESEARCH: Call research_business to learn about {req.business_name}.
2. DRAFT PROPOSAL: Call draft_proposal with the research results.
3. FACT-CHECK: Call fact_check_proposal to refine the proposal.
4. PHONE CALL: {"SKIP — user requested no call." if req.skip_call else f"Call call_business to call {req.phone} with the proposal context."}
5. CLASSIFY: {"SKIP." if req.skip_call else "Call classify_call_outcome with the call transcript."}
6. EMAIL: If the call outcome is 'interested' or 'agreed_to_email' (or if call was skipped), call send_outreach_email with a compelling HTML email.
7. SAVE: Call save_sdr_result with all the session data.

After each step, provide a brief status update.
At the end, summarize everything that happened."""

        # All specialist tools
        tools = [
            research_business,
            draft_proposal,
            fact_check_proposal,
            classify_call_outcome,
        ]

        # Add phone call tool only if not skipped and phone is available
        if not req.skip_call and req.phone:
            async def call_business(transcript_context: str = "") -> str:
                """Call the business on the phone with AI voice."""
                return await make_phone_call(
                    phone_number=req.phone,
                    business_name=req.business_name,
                    context=transcript_context,
                    proposal_summary="",
                )
            tools.append(call_business)

        # Email tool
        if req.email:
            async def send_outreach_email(subject: str, html_body: str) -> str:
                """Send an outreach email to the business."""
                return await send_email(
                    to_email=req.email,
                    subject=subject,
                    html_body=html_body,
                    business_name=req.business_name,
                )
            tools.append(send_outreach_email)

        # Save tool
        def save_sdr_result(
            research_summary: str = "",
            proposal_summary: str = "",
            call_transcript: str = "",
            call_outcome: str = "other",
            email_sent: bool = False,
            email_subject: str = "",
        ) -> str:
            """Save the SDR session results."""
            session_data = {
                "session_id": session_id,
                "lead_place_id": req.place_id,
                "business_name": req.business_name,
                "research_summary": research_summary[:5000],
                "proposal_summary": proposal_summary[:5000],
                "call_transcript": call_transcript[:5000],
                "call_outcome": call_outcome,
                "email_sent": email_sent,
                "email_subject": email_subject,
                "created_at": datetime.utcnow().isoformat(),
            }
            # Update in-memory
            sdr_sessions[session_id] = SDRResult(**session_data)
            # Persist to BQ
            return save_sdr_session(session_data)

        tools.append(save_sdr_result)

        result = await runner.run(
            input=instructions,
            model=DEFAULT_MODEL,
            tools=tools,
            max_steps=15,
        )

        # Notify UI: completed
        await notify_ui(callback_url, AgentCallback(
            agent_type=AgentType.SDR,
            event="sdr_completed",
            business_name=req.business_name,
            business_id=req.place_id,
            message=f"SDR outreach completed for {req.business_name}",
            data={
                "session_id": session_id,
                "summary": result.final_output[:1000] if result.final_output else "",
            },
        ))

        # Update lead status in BQ
        if req.place_id:
            update_lead_status(req.place_id, "contacted")

        return {
            "status": "success",
            "session_id": session_id,
            "business_name": req.business_name,
            "summary": result.final_output,
        }

    except Exception as e:
        logger.error(f"SDR pipeline failed for {req.business_name}: {e}")
        await notify_ui(callback_url, AgentCallback(
            agent_type=AgentType.SDR,
            event="error",
            business_name=req.business_name,
            message=f"SDR failed: {str(e)}",
        ))
        return {"status": "error", "message": str(e)}


@app.get("/api/sessions")
async def get_sessions():
    return {"sessions": {k: v.model_dump() for k, v in sdr_sessions.items()}}
