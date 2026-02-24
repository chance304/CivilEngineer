"""
GIS router — jurisdiction auto-detection from GPS coordinates.

This is a public endpoint (no auth required) — it returns only publicly
available jurisdiction metadata, no firm data is touched.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from civilengineer.gis.jurisdiction_map import resolve_jurisdiction
from civilengineer.gis.nominatim import NominatimError, reverse_geocode

router = APIRouter(prefix="/gis", tags=["gis"])


class JurisdictionDetection(BaseModel):
    jurisdiction: str
    jurisdiction_version: str
    local_body: str | None
    city: str | None
    state: str | None
    country: str | None
    country_code: str | None
    confidence: float
    match_level: str   # "city" | "state" | "country" | "fallback"


@router.get("/resolve-jurisdiction", response_model=JurisdictionDetection)
async def resolve_jurisdiction_endpoint(
    lat: Annotated[float, Query(ge=-90.0, le=90.0)],
    lon: Annotated[float, Query(ge=-180.0, le=180.0)],
) -> JurisdictionDetection:
    """
    Reverse-geocode a GPS coordinate and return the best matching jurisdiction.

    No authentication required — returns only public jurisdiction metadata.
    """
    try:
        address = await reverse_geocode(lat, lon)
    except NominatimError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Reverse geocoding failed: {exc}",
        ) from exc

    country_code = address.get("country_code", "") or ""
    state        = (
        address.get("state")
        or address.get("state_district")
        or address.get("province")
        or ""
    )
    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
        or ""
    )
    country = address.get("country", "")

    match = resolve_jurisdiction(country_code, state, city)

    return JurisdictionDetection(
        jurisdiction=match.jurisdiction,
        jurisdiction_version=match.version,
        local_body=match.local_body,
        city=city or None,
        state=state or None,
        country=country or None,
        country_code=country_code or None,
        confidence=match.confidence,
        match_level=match.match_level,
    )
