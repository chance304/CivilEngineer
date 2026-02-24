"""
Interview question bank and adaptive logic.

Questions are structured prompt fragments that the interviewer node feeds
to the LLM. Each question has:
  - id         : unique identifier (matches answers dict key)
  - phase      : which interview phase it belongs to
  - prompt     : the text the LLM should present to the user
  - required   : whether the answer is mandatory before proceeding
  - depends_on : dict of {other_question_id: expected_value} — adaptive gating
  - extractor  : callable that parses the user's free-text answer into a typed value

The extractor functions are deterministic (no LLM). They parse common patterns:
  "3BHK", "3 bedrooms", "3 bed" → bedroom_count=3
  "2 floors", "G+2", "3 storey" → num_floors=3
  "modern", "traditional"       → style
  "yes", "no", "y", "n"         → bool
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from civilengineer.schemas.design import FinishSpec, FloorFinish, RoomType, StylePreference
from civilengineer.schemas.mep import MEPRequirements

# ---------------------------------------------------------------------------
# Question definition
# ---------------------------------------------------------------------------


@dataclass
class Question:
    id: str
    phase: str
    prompt: str
    required: bool = True
    depends_on: dict[str, Any] = field(default_factory=dict)
    extractor: Callable[[str], Any] | None = None
    help_text: str = ""


# ---------------------------------------------------------------------------
# Extractor functions
# ---------------------------------------------------------------------------


def extract_building_type(text: str) -> str:
    """Return 'residential', 'commercial', or 'mixed'."""
    t = text.lower()
    if any(w in t for w in ["commercial", "office", "shop", "retail", "store"]):
        return "commercial"
    if any(w in t for w in ["mix", "mixed", "part commercial", "shop+house"]):
        return "mixed"
    return "residential"


def extract_num_floors(text: str) -> int:
    """Parse floor count from text. 'G+2' → 3, '3 storey' → 3, '2 floors' → 2."""
    text = text.strip()
    # G+N pattern (Ground + N upper floors)
    m = re.search(r"g\+\s*(\d+)", text, re.IGNORECASE)
    if m:
        return int(m.group(1)) + 1
    # "N storey/floor/level"
    m = re.search(r"(\d+)\s*(?:storey|floor|level|story)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Plain number
    m = re.search(r"\b([1-9])\b", text)
    if m:
        return int(m.group(1))
    return 2  # default


def extract_bhk(text: str) -> dict[str, int]:
    """
    Parse BHK notation and synonyms.

    Returns dict with bedroom_count, bathroom_count, hall_count.
    '3BHK' → {'bedroom_count': 3, 'bathroom_count': 2, 'hall_count': 1}
    '2 bedrooms, 1 bathroom' → {'bedroom_count': 2, 'bathroom_count': 1}
    """
    t = text.lower()
    result: dict[str, int] = {}

    # BHK notation: 2BHK, 3BHK, 4BHK
    m = re.search(r"(\d+)\s*bhk", t)
    if m:
        n = int(m.group(1))
        result["bedroom_count"] = n
        # BHK convention: bathrooms = bedrooms - 1 (at least 1)
        result["bathroom_count"] = max(1, n - 1)
        result["hall_count"] = 1
        return result

    # Explicit bedroom count
    m = re.search(r"(\d+)\s*(?:bed(?:room)?s?|br\b)", t)
    if m:
        result["bedroom_count"] = int(m.group(1))

    # Explicit bathroom count
    m = re.search(r"(\d+)\s*(?:bath(?:room)?s?|toilet|wc)", t)
    if m:
        result["bathroom_count"] = int(m.group(1))

    # Default: 1 of each if not specified
    result.setdefault("bedroom_count", 1)
    result.setdefault("bathroom_count", 1)
    return result


def extract_style(text: str) -> StylePreference:
    t = text.lower()
    if any(w in t for w in ["newari", "traditional nepali", "nepal trad"]):
        return StylePreference.NEWARI
    if any(w in t for w in ["traditional", "classic", "vernacular"]):
        return StylePreference.TRADITIONAL
    if any(w in t for w in ["minimal", "minimalist", "simple", "clean"]):
        return StylePreference.MINIMAL
    if any(w in t for w in ["classical", "georgian", "colonial"]):
        return StylePreference.CLASSICAL
    return StylePreference.MODERN  # default


def extract_bool(text: str) -> bool:
    t = text.lower().strip()
    return t.startswith(("y", "yes", "true", "1", "ok", "sure", "definitely"))


def extract_special_rooms(text: str) -> list[RoomType]:
    """Extract additional room types from free-text description."""
    t = text.lower()
    extras: list[RoomType] = []
    if any(w in t for w in ["office", "home office", "study", "work room"]):
        extras.append(RoomType.HOME_OFFICE)
    if any(w in t for w in ["pooja", "puja", "prayer", "temple", "mandir"]):
        extras.append(RoomType.POOJA_ROOM)
    if any(w in t for w in ["garage", "car park", "parking", "car port"]):
        extras.append(RoomType.GARAGE)
    if any(w in t for w in ["store", "storage", "utility"]):
        extras.append(RoomType.STORE)
    if any(w in t for w in ["terrace", "roof access", "rooftop"]):
        extras.append(RoomType.TERRACE)
    if any(w in t for w in ["balcony", "veranda", "verandah"]):
        extras.append(RoomType.BALCONY)
    return extras


# ---------------------------------------------------------------------------
# MEP extractor functions
# ---------------------------------------------------------------------------


def extract_high_load_appliances(text: str) -> list[str]:
    """Parse high-load appliance mentions from free text."""
    t = text.lower()
    appliances: list[str] = []
    if any(w in t for w in ["ac", "air condition", "air-condition", "split unit"]):
        appliances.append("AC_MASTER")
    if any(w in t for w in ["washing machine", "washer", "wm", "laundry"]):
        appliances.append("WM_UTILITY")
    if any(w in t for w in ["water heater", "geyser", "hot water", "boiler"]):
        appliances.append("WATER_HEATER_BATH1")
    if any(w in t for w in ["oven", "electric oven", "microwave oven"]):
        appliances.append("OVEN_KITCHEN")
    if any(w in t for w in ["lift", "elevator"]):
        appliances.append("ELEVATOR")
    return appliances


def extract_solar_pv_kw(text: str) -> float | None:
    """Extract solar PV kW target from text. '3kW solar' → 3.0."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*kw", text, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


def extract_plumbing_grade(text: str) -> str:
    """Return 'basic', 'standard', or 'premium'."""
    t = text.lower()
    if any(w in t for w in ["premium", "luxury", "high-end", "upscale"]):
        return "premium"
    if any(w in t for w in ["basic", "budget", "simple", "economy"]):
        return "basic"
    return "standard"


def extract_lighting_preference(text: str) -> str:
    """Return 'natural-first', 'task', or 'feature'."""
    t = text.lower()
    if any(w in t for w in ["feature", "mood", "accent", "decorative"]):
        return "feature"
    if any(w in t for w in ["task", "work", "functional"]):
        return "task"
    return "natural-first"


# ---------------------------------------------------------------------------
# Finish extractor functions
# ---------------------------------------------------------------------------


def extract_floor_finish(text: str) -> FloorFinish:
    """Parse a flooring material preference from free text.

    Returns a ``FloorFinish`` enum value.
    Examples: 'marble' → MARBLE, 'vitrified tile' → TILE, 'hardwood' → HARDWOOD
    """
    t = text.lower()
    if any(w in t for w in ["marble", "italian marble", "imported marble"]):
        return FloorFinish.MARBLE
    if any(w in t for w in ["granite", "granite slab"]):
        return FloorFinish.GRANITE
    if any(w in t for w in ["hardwood", "wood floor", "timber floor", "parquet", "oak", "teak"]):
        return FloorFinish.HARDWOOD
    if any(w in t for w in ["mosaic", "mosaic tile"]):
        return FloorFinish.MOSAIC
    if any(w in t for w in ["vinyl", "laminate", "pvc", "luxury vinyl"]):
        return FloorFinish.VINYL
    if any(w in t for w in ["concrete", "screed", "plain", "bare"]):
        return FloorFinish.CONCRETE
    return FloorFinish.TILE   # default: standard ceramic / vitrified tile


def extract_ceiling_finish(text: str) -> str:
    """Parse ceiling finish preference.

    Returns one of: 'plaster', 'pop', 'false_ceiling', 'wood_panel'.
    """
    t = text.lower()
    if any(w in t for w in ["wood", "timber", "panel", "wooden panel"]):
        return "wood_panel"
    if any(w in t for w in ["false ceiling", "false", "gypsum board", "t-grid", "grid"]):
        return "false_ceiling"
    if any(w in t for w in ["pop", "plaster of paris", "cornice", "decorative"]):
        return "pop"
    return "plaster"   # default: plain plaster


def extract_wall_paint(text: str) -> str:
    """Parse wall paint / finish preference.

    Returns one of: 'standard', 'premium', 'texture'.
    """
    t = text.lower()
    if any(w in t for w in ["texture", "textured", "3d paint", "stucco"]):
        return "texture"
    if any(w in t for w in ["premium", "luxury", "high quality", "branded", "asian paints royale"]):
        return "premium"
    return "standard"


# ---------------------------------------------------------------------------
# India-specific extractor functions
# ---------------------------------------------------------------------------


def extract_fsi_zone(text: str) -> str:
    """
    Parse FSI / FAR zone from free text (Maharashtra DCPR 2034 / NBC 2016).

    Returns one of: 'R1', 'R2', 'C1', 'C2', 'mixed', 'unknown'.
    - R1 = low-density residential (FSI 1.0)
    - R2 = medium-density residential (FSI 1.5–2.5)
    - C1 = neighbourhood commercial
    - C2 = major commercial
    """
    t = text.upper()
    if any(w in t for w in ["R1", "RESIDENTIAL 1", "LOW DENSITY"]):
        return "R1"
    if any(w in t for w in ["R2", "RESIDENTIAL 2", "MEDIUM DENSITY"]):
        return "R2"
    if any(w in t for w in ["C2", "COMMERCIAL 2", "MAJOR COMMERCIAL", "HIGH COMMERCIAL"]):
        return "C2"
    if any(w in t for w in ["C1", "COMMERCIAL 1", "NEIGHBOURHOOD COMMERCIAL", "LOCAL COMMERCIAL"]):
        return "C1"
    if any(w in t for w in ["MIXED", "MIX USE", "MIXED USE"]):
        return "mixed"
    return "unknown"


def extract_unit_preference(text: str) -> str:
    """
    Parse preferred measurement unit from free text.

    Returns 'sqft' or 'sqm'.
    India commonly uses sq ft for residential; sq m for official plans.
    """
    t = text.lower()
    if any(w in t for w in ["sq ft", "sqft", "square feet", "square foot", "feet"]):
        return "sqft"
    return "sqm"


def extract_basement_parking(text: str) -> dict[str, object]:
    """
    Parse basement parking requirement from free text.

    Returns dict: {'required': bool, 'car_count': int}.
    Examples:
      'yes, 2 cars' → {'required': True, 'car_count': 2}
      'no basement' → {'required': False, 'car_count': 0}
    """
    t = text.lower()
    if any(w in t for w in ["no ", "not ", "don't ", "dont ", "none", "no basement"]):
        return {"required": False, "car_count": 0}

    m = re.search(r"(\d+)\s*(?:car|vehicle|parking\s*space)", t)
    car_count = int(m.group(1)) if m else 1

    has_basement = any(w in t for w in [
        "yes", "basement", "underground", "covered parking", "stilt", "podium"
    ])
    return {"required": has_basement or car_count > 0, "car_count": car_count}


def extract_rera_applicable(text: str) -> bool:
    """Return True if RERA compliance is explicitly required."""
    t = text.lower()
    if re.search(r"\bno\b", t) or any(w in t for w in ["not applicable", "n/a", "doesn't apply"]):
        return False
    if re.search(r"\bnot\b", t):
        return False
    if any(w in t for w in ["yes", "rera", "required", "applicable", "mandatory"]):
        return True
    # Default: RERA applies to all residential projects >500 sqm in India (2016 Act)
    return True


def extract_india_style(text: str) -> str:
    """
    Parse Indian architectural style from free text.

    Returns a StylePreference value string.
    """
    t = text.lower()
    if any(w in t for w in ["south indian", "kerala", "chettinad", "dravidian", "tamil"]):
        return "south_indian"
    if any(w in t for w in ["contemporary", "indo-modern", "fusion", "semi-modern"]):
        return "contemporary"
    if any(w in t for w in ["newari", "nepali traditional"]):
        return "newari"
    if any(w in t for w in ["traditional", "classic", "vernacular", "mughal", "rajasthani"]):
        return "traditional"
    if any(w in t for w in ["minimal", "minimalist", "simple", "clean"]):
        return "minimal"
    return "modern"


# ---------------------------------------------------------------------------
# Question bank
# ---------------------------------------------------------------------------


QUESTIONS: list[Question] = [
    Question(
        id="building_type",
        phase="building_type",
        prompt=(
            "What type of building is this? "
            "(Residential house, commercial building, or mixed-use?)"
        ),
        extractor=extract_building_type,
        help_text="Say 'residential', 'commercial', or 'mixed'.",
    ),
    Question(
        id="num_floors",
        phase="program",
        prompt=(
            "How many floors should the building have? "
            "(You can say '2 floors', 'G+1', '3 storey', etc.)"
        ),
        extractor=extract_num_floors,
        help_text="Examples: '2 floors', 'G+2', '3 storey'.",
    ),
    Question(
        id="bhk_config",
        phase="rooms",
        prompt=(
            "How many bedrooms do you need? "
            "(You can say '3BHK', '3 bedrooms 2 bathrooms', etc.)"
        ),
        extractor=extract_bhk,
        depends_on={"building_type": "residential"},
        help_text="Examples: '3BHK', '2 bedrooms 1 bathroom'.",
    ),
    Question(
        id="master_bedroom",
        phase="rooms",
        prompt="Should one bedroom be a master bedroom with an attached bathroom?",
        extractor=extract_bool,
        depends_on={"building_type": "residential"},
        required=False,
        help_text="Yes or no.",
    ),
    Question(
        id="style",
        phase="style",
        prompt=(
            "What architectural style do you prefer? "
            "(Modern / Traditional / Minimal / Newari / Classical)"
        ),
        extractor=extract_style,
        required=False,
        help_text="Examples: 'Modern', 'Traditional', 'Minimal'.",
    ),
    Question(
        id="vastu",
        phase="vastu",
        prompt="Should the design follow Vastu Shastra guidelines?",
        extractor=extract_bool,
        required=False,
        help_text="Yes or no.",
    ),
    Question(
        id="special_rooms",
        phase="special",
        prompt=(
            "Any special rooms needed? "
            "(e.g. home office, pooja room, garage, store, terrace, balcony)"
        ),
        extractor=extract_special_rooms,
        required=False,
        help_text="List any extra rooms. Say 'none' if not needed.",
    ),
    Question(
        id="notes",
        phase="constraints",
        prompt=(
            "Any other specific requirements or constraints? "
            "(e.g. specific room positions, budget notes, client preferences)"
        ),
        required=False,
        extractor=lambda t: t.strip(),
        help_text="Say 'none' or describe any constraints.",
    ),
    # MEP questions
    Question(
        id="high_load_appliances",
        phase="mep",
        prompt=(
            "Which high-load electrical appliances will be installed? "
            "(e.g. air conditioning, washing machine, water heater, electric oven, lift)"
        ),
        required=False,
        extractor=extract_high_load_appliances,
        help_text="List appliances or say 'none'.",
    ),
    Question(
        id="solar_pv",
        phase="mep",
        prompt="Do you want solar PV panels installed? (yes/no)",
        required=False,
        extractor=extract_bool,
        help_text="Yes or no.",
    ),
    Question(
        id="solar_pv_kw",
        phase="mep",
        prompt="What solar PV capacity do you need? (e.g. '3kW', '5kW')",
        required=False,
        depends_on={"solar_pv": True},
        extractor=extract_solar_pv_kw,
        help_text="Specify kW target, e.g. '3kW'.",
    ),
    Question(
        id="solar_water_heating",
        phase="mep",
        prompt="Should solar water heating be included?",
        required=False,
        extractor=extract_bool,
        help_text="Yes or no.",
    ),
    Question(
        id="plumbing_grade",
        phase="mep",
        prompt=(
            "What plumbing fixture grade do you prefer? "
            "(Basic / Standard / Premium)"
        ),
        required=False,
        extractor=extract_plumbing_grade,
        help_text="Basic = economy fittings, Standard = mid-range, Premium = luxury.",
    ),
    Question(
        id="lighting_preference",
        phase="mep",
        prompt=(
            "What lighting style do you prefer? "
            "(Natural-first / Task lighting / Feature/mood lighting)"
        ),
        required=False,
        extractor=extract_lighting_preference,
        help_text="Natural-first maximises daylight; Task = practical; Feature = decorative.",
    ),
    # Finish questions
    Question(
        id="floor_finish_dry",
        phase="finishes",
        prompt=(
            "What flooring material do you prefer for living areas and bedrooms? "
            "(Tile / Marble / Granite / Hardwood / Vinyl / Concrete)"
        ),
        required=False,
        extractor=extract_floor_finish,
        help_text=(
            "Tile = standard ceramic/vitrified; Marble = premium imported; "
            "Granite = mid-premium; Hardwood = timber; Vinyl = budget laminate."
        ),
    ),
    Question(
        id="floor_finish_wet",
        phase="finishes",
        prompt=(
            "What flooring for wet areas — bathrooms and kitchen? "
            "(Tile / Marble / Granite / Mosaic)"
        ),
        required=False,
        extractor=extract_floor_finish,
        help_text="Anti-slip tile is recommended for wet areas. Mosaic is popular in bathrooms.",
    ),
    Question(
        id="ceiling_finish",
        phase="finishes",
        prompt=(
            "What ceiling finish do you prefer? "
            "(Plain plaster / POP cornice / False ceiling / Wood panel)"
        ),
        required=False,
        extractor=extract_ceiling_finish,
        help_text=(
            "Plain plaster = budget; POP cornice = decorative edges; "
            "False ceiling = gypsum grid; Wood panel = premium timber."
        ),
    ),
    Question(
        id="wall_paint",
        phase="finishes",
        prompt="What wall paint quality do you prefer? (Standard / Premium / Texture finish)",
        required=False,
        extractor=extract_wall_paint,
        help_text="Standard = economy emulsion; Premium = branded washable paint; Texture = 3D/stucco effect.",
    ),
    # India-specific questions (shown when jurisdiction starts with "IN")
    Question(
        id="india_fsi_zone",
        phase="india_specific",
        prompt=(
            "What is the FSI/FAR zone for this plot? "
            "(e.g. R1 — low-density residential, R2 — medium-density, "
            "C1/C2 — commercial, Mixed use)"
        ),
        required=False,
        extractor=extract_fsi_zone,
        help_text="R1 = FSI 1.0; R2 = FSI 1.5–2.5; C1/C2 = commercial. "
                  "Check DCPR 2034 (Mumbai), BDA (Bangalore), or local DP.",
    ),
    Question(
        id="india_unit_preference",
        phase="india_specific",
        prompt="Do you prefer measurements shown in sq ft or sq m?",
        required=False,
        extractor=extract_unit_preference,
        help_text="Sq ft is common for Indian residential projects; sq m is used in official plans.",
    ),
    Question(
        id="india_basement_parking",
        phase="india_specific",
        prompt="Do you need basement or stilt parking? If yes, for how many cars?",
        required=False,
        extractor=extract_basement_parking,
        help_text="Examples: 'Yes, 2 cars', 'Stilt parking for 1 car', 'No basement'.",
    ),
    Question(
        id="india_rera_applicable",
        phase="india_specific",
        prompt=(
            "Is RERA (Real Estate Regulation and Development Act) compliance required? "
            "Projects >500 sqm built-up area or >8 units require RERA registration."
        ),
        required=False,
        extractor=extract_rera_applicable,
        help_text="Yes = RERA applies; No = project is below threshold.",
    ),
    Question(
        id="india_sunken_slab",
        phase="india_specific",
        prompt="Should bathrooms have a sunken slab for concealed plumbing? (Common in India)",
        required=False,
        extractor=extract_bool,
        help_text="Sunken slab lowers the bathroom floor to hide plumbing pipes.",
    ),
]

# Index for quick lookup
QUESTION_BY_ID: dict[str, Question] = {q.id: q for q in QUESTIONS}


# ---------------------------------------------------------------------------
# Answer → DesignRequirements assembly
# ---------------------------------------------------------------------------


def answers_to_requirements(
    answers: dict[str, Any],
    project_id: str,
    jurisdiction: str = "NP-KTM",
    road_width_m: float | None = None,
) -> dict:
    """
    Convert collected interview answers into a DesignRequirements dict.

    Returns a plain dict (JSON-serialisable) that can be validated with
    DesignRequirements.model_validate().
    """
    num_floors   = answers.get("num_floors", 2)
    bhk          = answers.get("bhk_config", {"bedroom_count": 2, "bathroom_count": 1})
    has_master   = answers.get("master_bedroom", True)
    style        = answers.get("style", StylePreference.MODERN)
    vastu        = answers.get("vastu", False)
    special      = answers.get("special_rooms", [])
    notes_text   = answers.get("notes", "")

    bedroom_count  = bhk.get("bedroom_count", 2)
    bathroom_count = bhk.get("bathroom_count", 1)

    rooms: list[dict] = []

    # Ground floor essentials
    rooms.append({"room_type": RoomType.LIVING_ROOM.value})
    rooms.append({"room_type": RoomType.DINING_ROOM.value})
    rooms.append({"room_type": RoomType.KITCHEN.value})

    # Bedrooms
    if has_master and bedroom_count >= 1:
        rooms.append({"room_type": RoomType.MASTER_BEDROOM.value})
        bedroom_count -= 1

    for _ in range(bedroom_count):
        rooms.append({"room_type": RoomType.BEDROOM.value})

    # Bathrooms
    for _ in range(bathroom_count):
        rooms.append({"room_type": RoomType.BATHROOM.value})

    # Toilet on ground floor
    rooms.append({"room_type": RoomType.TOILET.value})

    # Staircase if multi-floor
    if num_floors > 1:
        rooms.append({"room_type": RoomType.STAIRCASE.value})

    # Special rooms
    for rtype in special:
        rooms.append({"room_type": rtype.value})

    # MEP requirements
    mep_req = MEPRequirements(
        high_load_appliances=answers.get("high_load_appliances", []),
        solar_pv=answers.get("solar_pv", False),
        solar_pv_kw=answers.get("solar_pv_kw"),
        solar_water_heating=answers.get("solar_water_heating", False),
        plumbing_grade=answers.get("plumbing_grade", "standard"),
        lighting_preference=answers.get("lighting_preference", "natural-first"),
    )

    # Finish overrides: map interview answers to room-type groups
    finish_overrides: dict[str, dict] = {}

    dry_finish = answers.get("floor_finish_dry")
    wet_finish = answers.get("floor_finish_wet")
    ceiling    = answers.get("ceiling_finish", "plaster")
    wall_paint = answers.get("wall_paint", "standard")

    if dry_finish is not None:
        dry_spec = FinishSpec(
            flooring=dry_finish,
            wall_paint=wall_paint,
            ceiling=ceiling,
        )
        for room_type in (
            RoomType.MASTER_BEDROOM, RoomType.BEDROOM,
            RoomType.LIVING_ROOM, RoomType.DINING_ROOM,
            RoomType.HOME_OFFICE, RoomType.POOJA_ROOM,
        ):
            finish_overrides[room_type.value] = dry_spec.model_dump()

    if wet_finish is not None:
        wet_spec = FinishSpec(
            flooring=wet_finish,
            wall_paint=wall_paint,
            ceiling=ceiling,
        )
        for room_type in (RoomType.BATHROOM, RoomType.TOILET, RoomType.KITCHEN):
            finish_overrides[room_type.value] = wet_spec.model_dump()

    return {
        "project_id": project_id,
        "jurisdiction": jurisdiction,
        "num_floors": num_floors,
        "rooms": rooms,
        "style": style.value if isinstance(style, StylePreference) else style,
        "vastu_compliant": vastu,
        "road_width_m": road_width_m,
        "notes": notes_text,
        "mep_requirements": mep_req.model_dump(),
        "finish_overrides": finish_overrides,
    }


# ---------------------------------------------------------------------------
# Adaptive gating
# ---------------------------------------------------------------------------


def questions_for_phase(phase: str, answers: dict[str, Any]) -> list[Question]:
    """Return questions that are active for this phase given collected answers."""
    result = []
    for q in QUESTIONS:
        if q.phase != phase:
            continue
        # Check depends_on: question is only active if all dependencies satisfied
        active = True
        for dep_id, expected_val in q.depends_on.items():
            actual = answers.get(dep_id)
            if actual != expected_val:
                active = False
                break
        if active:
            result.append(q)
    return result


def get_feasibility_warnings(
    answers: dict[str, Any],
    plot_area_sqm: float | None,
) -> list[str]:
    """
    Return advisory messages based on answers and plot size.
    Called after the rooms phase to give early feedback.
    """
    warnings: list[str] = []
    bhk = answers.get("bhk_config", {})
    bedroom_count = bhk.get("bedroom_count", 0)
    num_floors = answers.get("num_floors", 2)

    if plot_area_sqm and plot_area_sqm < 500 and bedroom_count >= 3:
        warnings.append(
            f"Plot area {plot_area_sqm:.0f} sqm may be tight for a {bedroom_count}BHK. "
            "Consider reducing to 2BHK or increasing num_floors."
        )
    if num_floors > 3 and not answers.get("vastu"):
        pass  # no warning
    if bedroom_count >= 4 and num_floors < 2:
        warnings.append(
            f"{bedroom_count} bedrooms on 1 floor will require a large plot. "
            "Consider adding a second floor."
        )
    return warnings
