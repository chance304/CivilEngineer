"""
Async Nominatim (OpenStreetMap) reverse-geocoding client.

Uses only httpx — no geopy, no geopandas, no PostGIS.
Complies with OSM Nominatim usage policy: single User-Agent header,
one request per lookup (no bulk geocoding).
"""

from __future__ import annotations

import httpx

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_USER_AGENT = "CivilEngineerApp/1.0"
_TIMEOUT_S = 10.0


class NominatimError(Exception):
    """Raised on network timeout, HTTP error, or API-level error response."""


async def reverse_geocode(lat: float, lon: float) -> dict:
    """
    Call Nominatim reverse-geocoding API and return a flattened address dict.

    Returns a dict with keys from the ``address`` sub-object merged with
    ``display_name`` at the top level.  Callers should use ``.get()`` with
    sensible defaults because not all fields are present in every response.

    Raises ``NominatimError`` on timeout, HTTP error, or if the response body
    contains an ``"error"`` key.
    """
    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
        "addressdetails": 1,
        "zoom": 10,
    }
    headers = {"User-Agent": _USER_AGENT, "Accept-Language": "en"}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            response = await client.get(_NOMINATIM_URL, params=params, headers=headers)
    except httpx.TimeoutException as exc:
        raise NominatimError(f"Nominatim request timed out: {exc}") from exc
    except httpx.HTTPError as exc:
        raise NominatimError(f"Nominatim HTTP error: {exc}") from exc

    if response.status_code != 200:
        raise NominatimError(
            f"Nominatim returned HTTP {response.status_code}: {response.text[:200]}"
        )

    data: dict = response.json()

    if "error" in data:
        raise NominatimError(f"Nominatim error: {data['error']}")

    address: dict = data.get("address", {})
    return {**address, "display_name": data.get("display_name", "")}
