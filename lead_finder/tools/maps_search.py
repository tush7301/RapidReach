"""
lead_finder/tools/maps_search.py
Google Maps Places API wrapper.
Searches for businesses in a city, filters by criteria (no website, min rating, etc.),
and returns structured lead data.
"""

from __future__ import annotations
import json
import logging
from typing import Any

import httpx

from common.config import GOOGLE_MAPS_API_KEY

logger = logging.getLogger(__name__)

PLACES_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

# Common chain names to exclude
CHAIN_KEYWORDS = {
    "starbucks", "mcdonald", "subway", "walmart", "target", "costco",
    "walgreens", "cvs", "7-eleven", "dunkin", "burger king", "wendy",
    "taco bell", "chick-fil-a", "domino", "pizza hut", "papa john",
}


def _is_chain(name: str) -> bool:
    lower = name.lower()
    return any(kw in lower for kw in CHAIN_KEYWORDS)


async def search_google_maps(
    city: str,
    business_types: list[str] | None = None,
    radius_km: int = 10,
    max_results: int = 20,
    exclude_chains: bool = True,
    min_rating: float = 0.0,
    only_without_website: bool = True,
) -> str:
    """
    Search Google Maps for businesses in a city.

    Args:
        city: The city to search in, e.g. "San Francisco, CA".
        business_types: Types of businesses like ["restaurant", "salon", "plumber"].
                        If empty, searches for "local business".
        radius_km: Search radius in kilometers.
        max_results: Maximum number of results to return.
        exclude_chains: Whether to exclude well-known chains.
        min_rating: Minimum Google rating to include.
        only_without_website: If True, only return businesses without a website.

    Returns:
        JSON string with a list of business leads.
    """
    if not GOOGLE_MAPS_API_KEY:
        return json.dumps({"error": "GOOGLE_MAPS_API_KEY not set", "leads": []})

    search_types = business_types if business_types else ["local business"]
    all_leads: list[dict[str, Any]] = []
    seen_place_ids: set[str] = set()

    async with httpx.AsyncClient(timeout=30) as client:
        for btype in search_types:
            query = f"{btype} in {city}"
            params = {
                "query": query,
                "radius": radius_km * 1000,
                "key": GOOGLE_MAPS_API_KEY,
            }

            try:
                resp = await client.get(PLACES_SEARCH_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"Maps search failed for '{query}': {e}")
                continue

            results = data.get("results", [])
            for place in results:
                if len(all_leads) >= max_results:
                    break

                place_id = place.get("place_id", "")
                if place_id in seen_place_ids:
                    continue
                seen_place_ids.add(place_id)

                name = place.get("name", "")
                rating = place.get("rating", 0)

                if exclude_chains and _is_chain(name):
                    continue
                if rating < min_rating:
                    continue

                # Fetch details to check for website
                detail = await _get_place_details(client, place_id)

                has_website = bool(detail.get("website"))
                if only_without_website and has_website:
                    continue

                lead = {
                    "place_id": place_id,
                    "business_name": name,
                    "address": place.get("formatted_address", ""),
                    "city": city,
                    "phone": detail.get("formatted_phone_number", ""),
                    "email": "",
                    "website": detail.get("website", ""),
                    "rating": rating,
                    "total_ratings": place.get("user_ratings_total", 0),
                    "business_type": btype,
                    "has_website": has_website,
                    "lead_status": "new",
                }
                all_leads.append(lead)

    return json.dumps({"leads": all_leads, "total": len(all_leads), "city": city})


async def _get_place_details(client: httpx.AsyncClient, place_id: str) -> dict:
    """Fetch detailed info for a single place."""
    try:
        resp = await client.get(
            PLACE_DETAILS_URL,
            params={
                "place_id": place_id,
                "fields": "formatted_phone_number,website,opening_hours,url",
                "key": GOOGLE_MAPS_API_KEY,
            },
        )
        resp.raise_for_status()
        return resp.json().get("result", {})
    except Exception as e:
        logger.warning(f"Place details failed for {place_id}: {e}")
        return {}
