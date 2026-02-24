"""
Static lookup table: (country_code, state, city) → jurisdiction code.

No network calls, no external dependencies.  All matching is lowercase
substring matching so minor Nominatim spelling variations are handled.

Confidence levels:
  1.00 — city-level match (most specific)
  0.85 — state/province-level match
  0.65 — country-level match
  0.40 — fallback (NP-KTM)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JurisdictionMatch:
    jurisdiction: str           # e.g. "NP-KTM"
    version: str                # e.g. "NBC_2020_KTM"
    local_body: str | None      # e.g. "KMC"
    confidence: float           # 0.0–1.0
    match_level: str            # "city" | "state" | "country" | "fallback"


# ---------------------------------------------------------------------------
# City-level table  (confidence = 1.0)
# Each entry: (country_code, state_fragment, city_fragment, JurisdictionMatch)
# Matching: all three strings must be substrings of the lowercase Nominatim values.
# ---------------------------------------------------------------------------

_CITY_TABLE: list[tuple[str, str, str, JurisdictionMatch]] = [
    # Nepal — Bagmati province
    ("np", "bagmati", "kathmandu",
     JurisdictionMatch("NP-KTM", "NBC_2020_KTM", "KMC",  1.0, "city")),
    ("np", "bagmati", "lalitpur",
     JurisdictionMatch("NP-LAL", "NBC_2020_KTM", "LLMC", 1.0, "city")),
    ("np", "bagmati", "bhaktapur",
     JurisdictionMatch("NP-BKT", "NBC_2020_KTM", "BkMC", 1.0, "city")),
    ("np", "bagmati", "kirtipur",
     JurisdictionMatch("NP-KTM", "NBC_2020_KTM", "KMC",  1.0, "city")),
    # Nepal — Gandaki province
    ("np", "gandaki", "pokhara",
     JurisdictionMatch("NP-PKR", "NBC_2020_PKR", "PMC",  1.0, "city")),

    # India — Maharashtra
    ("in", "maharashtra", "pune",
     JurisdictionMatch("IN-MH-PUN", "NBC_2016", "PMC",  1.0, "city")),
    ("in", "maharashtra", "pimpri",
     JurisdictionMatch("IN-MH-PUN", "NBC_2016", "PCMC", 1.0, "city")),
    ("in", "maharashtra", "nashik",
     JurisdictionMatch("IN-MH",     "NBC_2016", "NMC",  1.0, "city")),
    ("in", "maharashtra", "nagpur",
     JurisdictionMatch("IN-MH",     "NBC_2016", "NMC",  1.0, "city")),
    ("in", "maharashtra", "mumbai",
     JurisdictionMatch("IN-MH",     "NBC_2016", "MCGM", 1.0, "city")),

    # India — Karnataka
    ("in", "karnataka", "bengaluru",
     JurisdictionMatch("IN-KA", "NBC_2016", "BBMP", 1.0, "city")),
    ("in", "karnataka", "bangalore",
     JurisdictionMatch("IN-KA", "NBC_2016", "BBMP", 1.0, "city")),
    ("in", "karnataka", "mysuru",
     JurisdictionMatch("IN-KA", "NBC_2016", "MCC",  1.0, "city")),
    ("in", "karnataka", "mysore",
     JurisdictionMatch("IN-KA", "NBC_2016", "MCC",  1.0, "city")),

    # India — Delhi
    ("in", "delhi", "delhi",
     JurisdictionMatch("IN", "NBC_2016", "DDA", 1.0, "city")),

    # India — Tamil Nadu
    ("in", "tamil nadu", "chennai",
     JurisdictionMatch("IN", "NBC_2016", "GCC",  1.0, "city")),

    # India — Telangana
    ("in", "telangana", "hyderabad",
     JurisdictionMatch("IN", "NBC_2016", "GHMC", 1.0, "city")),

    # India — Gujarat
    ("in", "gujarat", "ahmedabad",
     JurisdictionMatch("IN", "NBC_2016", "AMC",  1.0, "city")),
]

# ---------------------------------------------------------------------------
# State-level table  (confidence = 0.85)
# Each entry: (country_code, state_fragment, JurisdictionMatch)
# ---------------------------------------------------------------------------

_STATE_TABLE: list[tuple[str, str, JurisdictionMatch]] = [
    # Nepal provinces
    ("np", "bagmati",
     JurisdictionMatch("NP-KTM", "NBC_2020_KTM", None, 0.85, "state")),
    ("np", "gandaki",
     JurisdictionMatch("NP-PKR", "NBC_2020_PKR", None, 0.85, "state")),
    # All other Nepal provinces fall through to country-level

    # India states
    ("in", "maharashtra",
     JurisdictionMatch("IN-MH", "NBC_2016", "MCGM", 0.85, "state")),
    ("in", "karnataka",
     JurisdictionMatch("IN-KA", "NBC_2016", None,   0.85, "state")),
    ("in", "delhi",
     JurisdictionMatch("IN",    "NBC_2016", "DDA",  0.85, "state")),
    ("in", "tamil nadu",
     JurisdictionMatch("IN",    "NBC_2016", None,   0.85, "state")),
    ("in", "telangana",
     JurisdictionMatch("IN",    "NBC_2016", None,   0.85, "state")),
    ("in", "gujarat",
     JurisdictionMatch("IN",    "NBC_2016", None,   0.85, "state")),
    ("in", "rajasthan",
     JurisdictionMatch("IN",    "NBC_2016", None,   0.85, "state")),
    ("in", "uttar pradesh",
     JurisdictionMatch("IN",    "NBC_2016", None,   0.85, "state")),
    ("in", "west bengal",
     JurisdictionMatch("IN",    "NBC_2016", None,   0.85, "state")),

    # USA states
    ("us", "california",
     JurisdictionMatch("US-CA", "CBC_2022", None,    0.85, "state")),
    ("us", "new york",
     JurisdictionMatch("US-CA", "IBC_2021", None,    0.85, "state")),
    ("us", "texas",
     JurisdictionMatch("US-CA", "IBC_2021", None,    0.85, "state")),
    ("us", "florida",
     JurisdictionMatch("US-CA", "IBC_2021", None,    0.85, "state")),
]

# ---------------------------------------------------------------------------
# Country-level table  (confidence = 0.65)
# ---------------------------------------------------------------------------

_COUNTRY_TABLE: dict[str, JurisdictionMatch] = {
    "np": JurisdictionMatch("NP",    "NBC_2020",  None, 0.65, "country"),
    "in": JurisdictionMatch("IN",    "NBC_2016",  None, 0.65, "country"),
    "gb": JurisdictionMatch("UK",    "BR_2023",   None, 0.65, "country"),
    "us": JurisdictionMatch("US-CA", "IBC_2021",  None, 0.65, "country"),
    "au": JurisdictionMatch("US-CA", "IBC_2021",  None, 0.65, "country"),  # placeholder
    "ca": JurisdictionMatch("US-CA", "IBC_2021",  None, 0.65, "country"),  # placeholder
}

# ---------------------------------------------------------------------------
# Fallback  (confidence = 0.40)
# ---------------------------------------------------------------------------

_FALLBACK = JurisdictionMatch("NP-KTM", "NBC_2020_KTM", None, 0.40, "fallback")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_jurisdiction(
    country_code: str,
    state: str,
    city: str,
) -> JurisdictionMatch:
    """
    Resolve a jurisdiction from Nominatim address components.

    All three inputs are expected to already be lowercase strings; the
    function also lowercases them for safety.  Matching is substring-based
    so small variations (e.g. "West Bengal" vs "West bengal") are handled.
    """
    cc    = country_code.lower().strip()
    state = state.lower().strip()
    city  = city.lower().strip()

    # 1. City-level (most specific)
    for (tcc, tstate, tcity, match) in _CITY_TABLE:
        if cc == tcc and tstate in state and tcity in city:
            return match

    # 2. State-level
    for (tcc, tstate, match) in _STATE_TABLE:
        if cc == tcc and tstate in state:
            return match

    # 3. Country-level
    if cc in _COUNTRY_TABLE:
        return _COUNTRY_TABLE[cc]

    # 4. Fallback
    return _FALLBACK
