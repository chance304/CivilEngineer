# Multi-Jurisdiction Building Codes

## Design Principle

The system is **jurisdiction-agnostic by design**. When a project is created,
the engineer selects a jurisdiction. The system then:
1. Loads the correct `RuleSet` for that jurisdiction (extracted from uploaded PDFs)
2. Adapts interview questions (e.g., seismic zone questions for Nepal, ADA for USA)
3. Enforces the correct numeric standards in the constraint solver
4. Labels compliance output with the correct code references
5. Uses correct units (metric for most countries, feet/inches for USA)

**Building codes are never manually compiled.** Admin uploads official PDF documents;
the system uses LLM extraction to produce structured rules. See `10-knowledge-base.md`.

---

## Jurisdiction Registry

Located at: `backend/src/civilengineer/jurisdiction/registry.py`

```python
JURISDICTION_REGISTRY = {
    # ── Nepal (primary / MVP jurisdiction) ─────────────────────────────
    "NP": JurisdictionMetadata(
        code="NP",
        country_name="Nepal",
        region_name=None,
        primary_code="NBC 2020",
        secondary_codes=[
            "NBC 105:2020 (Seismic Design)",
            "NBC 201:2012 (RC Buildings - MRT)",
            "NBC 202:2012 (Load Bearing Masonry - MRT)",
            "NBC 205:2012 (Mandatory Rules of Thumb)",
            "NBCR 2072 (Building Construction Regulations 2016)",
        ],
        code_version="NBC_2020",
        effective_date="2020-01-01",
        unit_system="metric",
        language="en",
        notes=(
            "Nepal National Building Code series. Most of Nepal is Seismic Zone V "
            "(very high risk). NBC 105:2020 governs seismic design. Traditional "
            "Newari architecture requires special consideration in KTM Valley. "
            "Land area locally measured in ropani (5476 sqft), anna, paisa, dhur."
        )
    ),
    "NP-KTM": JurisdictionMetadata(
        code="NP-KTM",
        country_name="Nepal",
        region_name="Kathmandu Valley",
        primary_code="NBC 2020",
        secondary_codes=[
            "NBC 105:2020 (Seismic Zone V)",
            "KMC Building Bylaws 2079 (Kathmandu Metropolitan City)",
            "DUDBC Guidelines (Dept. of Urban Development & Building Construction)",
        ],
        code_version="NBC_2020_KTM",
        effective_date="2022-01-01",
        unit_system="metric",
        language="en",
        notes=(
            "Kathmandu Valley includes KMC, Lalitpur Sub-Metropolitan City, "
            "Bhaktapur Municipality. Strict seismic zone V. Heritage conservation "
            "zones require traditional Newari facade elements. Road-frontage setback "
            "scales with road width (NBCR 2072 Table)."
        )
    ),
    "NP-PKR": JurisdictionMetadata(
        code="NP-PKR",
        country_name="Nepal",
        region_name="Pokhara",
        primary_code="NBC 2020",
        secondary_codes=[
            "NBC 105:2020 (Seismic Zone V)",
            "Pokhara Metropolitan City Building Bylaws",
        ],
        code_version="NBC_2020_PKR",
        effective_date="2022-01-01",
        unit_system="metric",
        language="en",
        notes=(
            "Pokhara Metropolitan City. Gateway to Annapurna region — tourism "
            "buildings common. Lakeside zone (Fewa) has height restrictions. "
            "Seismic Zone V applies."
        )
    ),

    # ── India ───────────────────────────────────────────────────────────
    "IN": JurisdictionMetadata(
        code="IN",
        country_name="India",
        region_name=None,
        primary_code="NBC 2016",
        secondary_codes=["SP 7 (2005)", "BIS IS 875", "IS 1893 (Seismic)"],
        code_version="NBC_2016",
        effective_date="2016-01-01",
        unit_system="metric",
        language="en",
        notes="National Building Code of India 2016. Room sizes in sq.m (converted to sqft internally)."
    ),
    "IN-MH": JurisdictionMetadata(
        code="IN-MH",
        country_name="India",
        region_name="Maharashtra",
        primary_code="NBC 2016",
        secondary_codes=["DCPR 2034", "UDCPR 2020"],
        code_version="NBC_2016_MH",
        effective_date="2020-01-01",
        unit_system="metric",
        language="en",
        notes="NBC + Maharashtra DCPR 2034 for Mumbai/MMR. UDCPR 2020 for rest of Maharashtra."
    ),
    "IN-KA": JurisdictionMetadata(
        code="IN-KA",
        country_name="India",
        region_name="Karnataka",
        primary_code="NBC 2016",
        secondary_codes=["BBMP Bylaws 2020", "BDA Regulations"],
        code_version="NBC_2016_KA",
        effective_date="2020-01-01",
        unit_system="metric",
        language="en",
        notes="NBC + BBMP bylaws for Bengaluru. BDA regulations for BDA-layout areas."
    ),

    # ── USA ─────────────────────────────────────────────────────────────
    "US": JurisdictionMetadata(
        code="US",
        country_name="United States",
        region_name=None,
        primary_code="IBC 2021",
        secondary_codes=["IRC 2021", "ASCE 7-22", "ADA Standards 2010"],
        code_version="IBC_2021",
        effective_date="2021-01-01",
        unit_system="imperial",
        language="en",
        notes="International Building Code 2021. Use state-specific codes when available."
    ),
    "US-CA": JurisdictionMetadata(
        code="US-CA",
        country_name="United States",
        region_name="California",
        primary_code="CBC 2022",
        secondary_codes=["IBC 2021", "Title 24 Part 6 (Energy)", "CFC 2022", "ADA Standards"],
        code_version="CBC_2022",
        effective_date="2023-01-01",
        unit_system="imperial",
        language="en",
        notes="California Building Code 2022. Stricter than IBC in seismic design and energy efficiency."
    ),
    "US-NY": JurisdictionMetadata(
        code="US-NY",
        country_name="United States",
        region_name="New York",
        primary_code="NYC BC 2022",
        secondary_codes=["IBC 2021", "ADA Standards"],
        code_version="NYC_BC_2022",
        effective_date="2022-01-01",
        unit_system="imperial",
        language="en",
        notes="New York City Building Code 2022. Significant deviations from IBC."
    ),

    # ── UK ──────────────────────────────────────────────────────────────
    "UK": JurisdictionMetadata(
        code="UK",
        country_name="United Kingdom",
        region_name="England and Wales",
        primary_code="Building Regulations 2023",
        secondary_codes=["Approved Document A (Structure)", "AD B (Fire)", "AD F (Ventilation)",
                         "AD L (Energy)", "AD M (Accessibility)", "BS 8300"],
        code_version="BR_2023",
        effective_date="2023-06-01",
        unit_system="metric",
        language="en",
        notes="England/Wales only. Scotland = Scottish Building Standards. Wales has some deviations."
    ),

    # ── China ───────────────────────────────────────────────────────────
    "CN": JurisdictionMetadata(
        code="CN",
        country_name="China",
        region_name=None,
        primary_code="GB 50352-2019",
        secondary_codes=["GB 50010 (Concrete)", "GB 50011 (Seismic)", "GB 50016 (Fire)"],
        code_version="GB_2019",
        effective_date="2019-10-01",
        unit_system="metric",
        language="zh",
        notes="General Code for Civil Buildings. Local provinces may add requirements."
    ),
    "CN-SH": JurisdictionMetadata(
        code="CN-SH",
        country_name="China",
        region_name="Shanghai",
        primary_code="GB 50352-2019",
        secondary_codes=["DGJ 08 (Shanghai local standards)", "GB 50011 (Seismic Zone 7)"],
        code_version="GB_2019_SH",
        effective_date="2020-01-01",
        unit_system="metric",
        language="zh",
        notes="Shanghai has additional requirements for residential density and green building."
    ),

    # ── Others (planned) ────────────────────────────────────────────────
    "AU": JurisdictionMetadata(
        code="AU",
        country_name="Australia",
        region_name=None,
        primary_code="NCC 2022",
        secondary_codes=["AS 1170 (Loading)", "AS 3600 (Concrete)", "AS 3959 (Bushfire)"],
        code_version="NCC_2022",
        effective_date="2023-05-01",
        unit_system="metric",
        language="en",
        notes="National Construction Code 2022. State/territory amendments apply."
    ),
    "AE-DU": JurisdictionMetadata(
        code="AE-DU",
        country_name="United Arab Emirates",
        region_name="Dubai",
        primary_code="Dubai Building Code 2021",
        secondary_codes=["IBC 2018 (structural ref)", "NFPA 101 (fire safety)"],
        code_version="DBC_2021",
        effective_date="2021-07-01",
        unit_system="metric",
        language="en",
        notes="Dubai Municipality Building Code. Abu Dhabi uses ADIBC."
    ),
    "SG": JurisdictionMetadata(
        code="SG",
        country_name="Singapore",
        region_name=None,
        primary_code="BCA Building Control Regulations",
        secondary_codes=["CP 79", "SS CP 5", "SCDF Fire Code"],
        code_version="BCA_2020",
        effective_date="2020-01-01",
        unit_system="metric",
        language="en",
        notes="Singapore BCA. Very strict enforcement. GFA limits enforced by URA."
    ),
}
```

---

## Room Size Standards by Jurisdiction

### Minimum Habitable Room Areas

| Room | Nepal (NBC) | India (NBC) | USA (IBC) | UK (BR) | China (GB) |
|------|------------|------------|-----------|---------|------------|
| Master Bedroom | 9.0 m² (97 sqft) | 9.5 m² (102 sqft) | 7.0 m² (75 sqft) | 6.5 m² (70 sqft)¹ | 10.0 m² (108 sqft) |
| Bedroom (secondary) | 7.0 m² (75 sqft) | 7.5 m² (81 sqft) | 7.0 m² (75 sqft) | 6.5 m² (70 sqft) | 8.0 m² (86 sqft) |
| Living Room | 9.3 m² (100 sqft) | 9.5 m² (102 sqft) | No minimum | No minimum | 10.0 m² (108 sqft) |
| Kitchen | 4.5 m² (48 sqft) | 5.0 m² (54 sqft) | No minimum | No minimum | 4.0 m² (43 sqft) |
| Bathroom (full) | 2.0 m² (22 sqft) | 1.8 m² (19 sqft) | No minimum | No minimum | 2.0 m² (22 sqft) |
| WC only | 1.2 m² (13 sqft) | 1.1 m² (12 sqft) | No minimum | No minimum | No minimum |
| Ceiling Height | 2.6 m (8.5 ft) | 2.75 m (9 ft) | 2.44 m (8 ft) | 2.3 m (7.5 ft) | 2.8 m (9.2 ft) |

¹ UK values vary by local authority; these are typical minimums.

Sources: NBC 205:2012 (Nepal), NBC 2016 Part 4 (India), IBC §1208 (USA), Approved Doc M (UK), GB 50352 §5.4 (China).

---

## Nepal-Specific: Setback Rules (NBCR 2072)

Setbacks in Nepal scale with the road width facing the plot:

| Road Width (front) | Setback Required | Notes |
|-------------------|-----------------|-------|
| < 6 m | 1.5 m | Narrow urban lanes (common in old KTM) |
| 6–9 m | 3.0 m | Standard residential roads |
| 9–12 m | 4.5 m | Collector roads |
| > 12 m | 6.0 m | Arterial roads |
| Side / Rear | 1.5 m min | Single-family; 2.0 m for multi-family |

KMC bylaws 2079 add: In heritage zones, ground floor height ≥ 3.5 m if commercial use.

---

## General Setback Standards by Jurisdiction

| Jurisdiction | Front | Rear | Side | Notes |
|-------------|-------|------|------|-------|
| Nepal (NBCR) | Road-width dependent (1.5–6 m) | 1.5–2.0 m | 1.5 m | See Nepal setback table above |
| India (NBC) | 3.0 m | 3.0 m | 1.5 m | Varies by plot size + local body |
| India (DCPR-Mumbai) | 4.5 m | 6.0 m | 1.5–2.5 m | BUA dependent |
| USA (typical suburban) | 6.1 m (20 ft) | 7.6 m (25 ft) | 1.5 m (5 ft) | Highly variable by zoning |
| UK | 3.0 m | 10.5 m | 1.0 m | NPPF policy |
| China (GB) | 6.0 m | 10.0 m | 3.0 m | Urban zones vary |
| UAE (Dubai) | 4.0 m | 5.0 m | 2.0 m | DBC Table 3.1 |
| Singapore | 7.5 m | 4.5 m | 2.0 m | URA planning parameters |

---

## Jurisdiction-Specific Features in the Interview

The `requirements_interview/questions.py` adapts questions based on jurisdiction:

### Nepal (NP, NP-KTM, NP-PKR)
Extra questions:
- "Is the building in Kathmandu Valley, Pokhara, or another area?"
- "What is the width of the road frontage? (determines setback)"
- "Traditional Newari style or modern?"
- "Is the site in a heritage conservation zone?"
- "Is the site prone to flooding?" (Terai regions)
- "Pooja kotha (prayer room) required?"
- "Plot measurement available in ropani/anna or square meters?"
- "How many floors? (Seismic zone V limits max height without engineer approval)"
- "Building material: RC frame or load-bearing masonry?"

Terminology used: "kotha" (room), "ropani", "m²", "tala" (floor)

### India (IN, IN-MH, IN-KA)
Extra questions:
- "Vastu compliant? Strict / flexible / no"
- "If vastu: specific room placement preferences?"
- "Pooja room required?"
- "Servant quarters?"

Terminology used: "BHK", "sqft", "pooja room", "servant quarters"

### USA (US, US-CA, US-NY)
Extra questions:
- "Is the site in a seismic zone?"
- "Is the site in a flood plain (FEMA map)?"
- "Will the building require ADA compliance?"
- "Energy compliance: Title 24?" (California only)
- "Garage: attached / detached / none?"

Terminology used: "master suite", "sq ft", "half bath", "full bath"

### UK (UK)
Extra questions:
- "Is the site in a conservation area or near a listed building?"
- "Permitted development or full planning application?"
- "Will Building Regulations Part M (accessibility) apply?"

Terminology used: "bedroom", "sq ft or sq m", "WC", "study"

### China (CN, CN-SH)
Extra questions:
- "Northern or southern bedroom preference?"
- "Feng shui considerations?" (optional)
- "Underground car park?"
- "Floor space index (FSI) quota from local government?"

Terminology used: "卧室 (bedroom)", "m²", "客厅 (living room)"

---

## Rule ID Convention

```
{COUNTRY}[_{REGION}]_{CODE_REFERENCE}

Examples:
  NP_NBC205_4.2        Nepal NBC 205 Section 4.2 (room areas)
  NP_NBC105_6.3        Nepal NBC 105 Section 6.3 (seismic)
  NP_KTM_BYLAW_3.1    Kathmandu Metropolitan City Bylaws Section 3.1
  IN_NBC_3.2.1         India NBC Part 4 Section 3.2.1 (bedroom area)
  IN_MH_DCPR_12.3      Maharashtra DCPR 2034 Table 12.3
  US_IBC_1208.4        US IBC Section 1208.4
  US_CA_CBC_1208.4     California CBC (amendment to IBC)
  US_ADA_4.1           US ADA Standards 4.1
  UK_ADM_B5.1          UK Approved Document M Section B5.1
  CN_GB50352_5.3       China GB 50352 Section 5.3
```

---

## Structural Standards by Jurisdiction

| Jurisdiction | Concrete | Steel | Seismic | Wind |
|-------------|----------|-------|---------|------|
| Nepal | NBC 105:2020 / IS 456 | IS 800:2007 | NBC 105 (Zone V) | NBC 206 |
| India | IS 456:2000 | IS 800:2007 | IS 1893:2016 (Zone I–V) | IS 875 Part 3 |
| USA | ACI 318-19 | AISC 360-22 | ASCE 7-22 (SDC A–F) | ASCE 7-22 |
| UK | EN 1992 (EC2) | EN 1993 (EC3) | EN 1998 (EC8) | EN 1991-1-4 |
| China | GB 50010-2010 | GB 50017-2017 | GB 50011-2010 | GB 50009 |
| Australia | AS 3600-2018 | AS 4100-2020 | AS 1170.4 | AS 1170.2 |

**Nepal seismic note:** NBC 105:2020 is the primary seismic design standard.
Most of Nepal sits in Seismic Zone V (the highest). The structural checker enforces:
- RC frame buildings: NBC 201 + NBC 105
- Load-bearing masonry: NBC 202 + NBC 205 (Mandatory Rules of Thumb)
- Brick/stone masonry: NBC 203

---

## Adding a New Jurisdiction

To add support for a new jurisdiction:

1. **Add to registry** (`jurisdiction/registry.py`):
   Add `JurisdictionMetadata` entry with all code references.

2. **Upload PDF(s) via admin** (`/admin/building-codes`):
   Firm admin uploads the official building code PDF. System runs LLM extraction.
   See `10-knowledge-base.md` for the full extraction workflow.

3. **Validate extracted rules** (admin UI):
   A senior engineer reviews the extracted `DesignRule` objects and activates them.

4. **Add interview adapter** (`requirements_interview/questions.py`):
   Add jurisdiction-specific question section + terminology mapping.

5. **Add interview prompt** (`requirements_interview/prompts/interview_{code}.md`):
   LLM system prompt adapted for the jurisdiction's design culture.

6. **Run indexing**:
   `python scripts/index_knowledge.py --jurisdiction {code}`

7. **Test**:
   `pytest tests/unit/test_jurisdiction_loader.py -k {code}`

**Minimum viable rule set for a new jurisdiction:**
- All room type minimum areas (bedroom, kitchen, bathroom at minimum)
- Standard setbacks (or note they vary by local body with a default)
- Ventilation requirements (kitchen + bathroom to external wall)
- Toilet-kitchen separation rule
- Staircase minimum width
- Ceiling height minimum
- Maximum FAR / plot coverage

---

## Unit Handling

All internal calculations use **meters** as the canonical unit.
Display units respect the project's jurisdiction and `dimension_units` preference.

```python
# src/civilengineer/jurisdiction/units.py

def to_meters(value: float, from_unit: str) -> float:
    conversions = {
        "m":     1.0,
        "mm":    0.001,
        "cm":    0.01,
        "ft":    0.3048,
        "in":    0.0254,
        "sqm":   1.0,        # area passthrough
        "sqft":  0.092903,   # 1 sqft = 0.092903 sqm
        "ropani": 508.72,    # 1 ropani = 508.72 sqm (Nepal land unit)
        "anna":  31.795,     # 1/16 ropani
        "dhur":  16.93,      # 1/20 ropani (Terai)
    }
    return value * conversions[from_unit]
```
