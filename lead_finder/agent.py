"""
lead_finder/agent.py
Main Lead Finder agent — FastAPI service + Dedalus DedalusRunner orchestration.

Architecture:
  Coordinator agent (cheap model) delegates to two specialist tools:
    1. search_google_maps — discovers businesses via Google Maps
    2. store_leads_bigquery — persists validated leads to BigQuery
  A dedup + merge step runs in Python between tool calls.
  Callbacks stream progress to the UI Client.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import FastAPI
from dedalus_labs import AsyncDedalus, DedalusRunner
from dotenv import load_dotenv

from common.config import DEFAULT_MODEL, UI_CLIENT_URL
from common.models import (
    AgentCallback,
    AgentType,
    FindLeadsRequest,
    Lead,
)
from lead_finder.tools.maps_search import search_google_maps
from lead_finder.tools.bigquery_utils import upload_leads

load_dotenv()
logger = logging.getLogger(__name__)

# ── In-memory lead store (for fast access before BQ round-trip) ──
discovered_leads: dict[str, Lead] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Lead Finder service starting")
    yield
    logger.info("Lead Finder service shutting down")


app = FastAPI(title="SalesShortcut Lead Finder", lifespan=lifespan)


# ── Helper: send callback to UI ─────────────────────────────

async def notify_ui(callback_url: str, payload: AgentCallback):
    """POST an event to the UI Client callback endpoint."""
    url = callback_url or f"{UI_CLIENT_URL}/agent_callback"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json=payload.model_dump())
    except Exception as e:
        logger.warning(f"UI callback failed: {e}")


# ── Helper: dedup + merge ────────────────────────────────────

def dedup_leads(raw_leads: list[dict]) -> list[Lead]:
    """Deduplicate by place_id, merge into Lead models."""
    seen: set[str] = set()
    unique: list[Lead] = []
    for ld in raw_leads:
        pid = ld.get("place_id", "")
        if pid and pid in seen:
            continue
        seen.add(pid)
        try:
            lead = Lead(**ld)
            unique.append(lead)
        except Exception:
            continue
    return unique


# ── Tools exposed to the agent ───────────────────────────────

async def find_businesses(
    city: str,
    business_types: list[str] | None = None,
    radius_km: int = 10,
    max_results: int = 20,
    exclude_chains: bool = True,
    min_rating: float = 0.0,
) -> str:
    """
    Search Google Maps for local businesses without websites in a given city.
    Returns JSON with discovered leads.
    """
    result = await search_google_maps(
        city=city,
        business_types=business_types,
        radius_km=radius_km,
        max_results=max_results,
        exclude_chains=exclude_chains,
        min_rating=min_rating,
        only_without_website=True,
    )
    return result


def store_leads(leads_json: str) -> str:
    """
    Persist a JSON list of leads to BigQuery.
    Input should be a JSON string of lead objects.
    Returns upload result summary.
    """
    try:
        leads = json.loads(leads_json)
        if isinstance(leads, dict):
            leads = leads.get("leads", [leads])
        return upload_leads(leads)
    except Exception as e:
        return json.dumps({"error": str(e), "uploaded": 0})


# ── API Endpoints ────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "lead_finder", "timestamp": datetime.utcnow().isoformat()}


@app.post("/find_leads")
async def find_leads_endpoint(req: FindLeadsRequest):
    """
    Start lead discovery for a city.
    Uses Dedalus DedalusRunner to orchestrate Maps search + storage.
    """
    callback_url = req.callback_url

    # Notify UI: started
    await notify_ui(callback_url, AgentCallback(
        agent_type=AgentType.LEAD_FINDER,
        event="search_started",
        message=f"Starting lead search in {req.city}",
        data={"city": req.city},
    ))

    try:
        client = AsyncDedalus()
        runner = DedalusRunner(client)

        instructions = f"""You are a lead discovery specialist. Your job is to find local businesses
in {req.city} that do NOT have websites — these are potential customers for web development services.

Steps:
1. Call find_businesses with city="{req.city}", business_types={json.dumps(req.business_types or ['restaurant', 'salon', 'plumber', 'dentist', 'auto repair'])},
   radius_km={req.radius_km}, max_results={req.max_results}, exclude_chains={req.exclude_chains}, min_rating={req.min_rating}.
2. Review the results — count how many leads were found.
3. Call store_leads with the leads JSON to persist them to the database.
4. Provide a final summary: how many leads found, what types, and any notable patterns.

Be thorough. If few results come back, try broader search terms."""

        result = await runner.run(
            input=instructions,
            model=DEFAULT_MODEL,
            tools=[find_businesses, store_leads],
            max_steps=8,
        )

        # Parse leads from the tool results and dedup
        leads_found: list[dict] = []
        if result.tool_results:
            for tr in result.tool_results:
                try:
                    parsed = json.loads(tr.get("result", "{}"))
                    if "leads" in parsed:
                        leads_found.extend(parsed["leads"])
                except Exception:
                    pass

        unique_leads = dedup_leads(leads_found)

        # Store in memory
        for lead in unique_leads:
            discovered_leads[lead.place_id] = lead

        # Notify UI: completed
        await notify_ui(callback_url, AgentCallback(
            agent_type=AgentType.LEAD_FINDER,
            event="search_completed",
            message=f"Found {len(unique_leads)} leads in {req.city}",
            data={
                "city": req.city,
                "total_leads": len(unique_leads),
                "leads": [ld.model_dump() for ld in unique_leads],
            },
        ))

        # Stream individual leads to UI
        for lead in unique_leads:
            await notify_ui(callback_url, AgentCallback(
                agent_type=AgentType.LEAD_FINDER,
                event="lead_found",
                business_id=lead.place_id,
                business_name=lead.business_name,
                status=lead.lead_status.value,
                message=f"Discovered: {lead.business_name} — {lead.address}",
                data=lead.model_dump(),
            ))

        return {
            "status": "success",
            "city": req.city,
            "total_leads": len(unique_leads),
            "leads": [ld.model_dump() for ld in unique_leads],
            "agent_summary": result.final_output,
        }

    except Exception as e:
        logger.error(f"Lead finding failed: {e}")
        await notify_ui(callback_url, AgentCallback(
            agent_type=AgentType.LEAD_FINDER,
            event="error",
            message=f"Lead search failed: {str(e)}",
        ))
        return {"status": "error", "message": str(e)}


@app.get("/api/leads")
async def get_leads():
    """Return all discovered leads from memory."""
    return {"leads": [ld.model_dump() for ld in discovered_leads.values()]}
