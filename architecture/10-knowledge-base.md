# Knowledge Base (Multi-Jurisdiction, v2)

## Design Philosophy

**Building codes are never manually compiled.**
Admin uploads the official PDF documents. The system extracts rules using LLM and
stores them in the database. A human engineer reviews and approves the extracted rules
before they are activated. This makes the knowledge base:

- **Traceable** — every rule links to its source PDF page and verbatim text
- **Auditable** — extraction logs, reviewer actions, and approval timestamps recorded
- **Updatable** — upload a new code version PDF; old versions remain for existing projects
- **LLM-verified, human-approved** — extraction confidence scores flag uncertain rules

The LLM handles qualitative reasoning only. Numeric constraints (areas, setbacks)
are enforced deterministically by the rule engine + OR-Tools.

---

## Storage Architecture

```
Layer 1: PostgreSQL — jurisdiction_rules table
    ├── All active DesignRule objects for all jurisdictions
    ├── Versioned (effective_from, superseded_by)
    ├── Firm overrides stored alongside base rules (is_overridden, override_value)
    ├── Source-linked: each rule references its BuildingCodeDocument + page number
    └── Admin UI: firm_admin can view/override rules for their projects

Layer 2: PostgreSQL — extracted_rules table (staging area)
    ├── Rules extracted by LLM but not yet reviewed/approved
    ├── Each has: source_text (verbatim PDF text), source_page, confidence score
    ├── Reviewer workflow: approve → copies to jurisdiction_rules; reject → stays staged
    └── Cleared after review is complete

Layer 3: ChromaDB — per-jurisdiction collections
    ├── Collection per jurisdiction: rules_NP, rules_IN, rules_US_CA, etc.
    ├── Each collection: rule descriptions + raw PDF text chunks
    ├── Queried by plan_node for context-aware qualitative reasoning
    └── Rebuilt by Celery index_job when rules are activated or PDFs change

Layer 4: S3 — building code PDF storage
    ├── Path: building-codes/{firm_id}/{doc_id}/{filename}.pdf
    ├── Persisted permanently (even after activation, for audit)
    └── Referenced by BuildingCodeDocumentModel.s3_key
```

---

## Building Code Upload Workflow

```
1. firm_admin goes to /admin/building-codes
   → Selects jurisdiction (e.g. NP-KTM)
   → Uploads official PDF (e.g. "nbc_205_2012.pdf")
   → Enters code name + version
   → System stores PDF in S3 → creates BuildingCodeDocumentModel (status: "uploaded")

2. Firm admin clicks "Extract Rules"
   → API queues Celery code_extraction_job
   → Status changes to "extracting"

3. code_extraction_job runs:
   a. pdfplumber reads PDF → splits into 500-token overlapping chunks
   b. For each chunk: LLM prompt extracts DesignRule candidates
   c. Each extracted rule stored in extracted_rules table with confidence score
   d. High-confidence rules (>0.85) flagged for quick approval
   e. Low-confidence rules (< 0.60) flagged for mandatory manual review
   f. Status changes to "review"
   g. WebSocket event: "building_code.extraction_complete"

4. firm_admin / senior_engineer goes to /admin/building-codes/{id}/review
   → Table shows all extracted rules with:
     - Source section + verbatim PDF text
     - Proposed rule_id, category, severity, numeric_value
     - Confidence score (color-coded)
     - Approve / Reject / Edit buttons per rule
   → Reviewer can edit: severity (hard/soft/advisory), numeric_value, rule_id
   → Reviewer approves individual rules

5. After review, admin clicks "Activate"
   → Approved rules copied to jurisdiction_rules table (status: "active")
   → Rejected rules remain in extracted_rules (status = rejected, not copied)
   → ChromaDB collection for this jurisdiction rebuilt (Celery index_job)
   → BuildingCodeDocumentModel.status = "active"
   → Existing projects using the jurisdiction pick up new rules on next design job
```

---

## LLM Rule Extraction — Prompt Design

The extraction uses structured output (Pydantic schema as response format).
Separate prompts for different rule categories to improve precision:

### Room Size Extraction Prompt (`extract_room_rules.md`)
```
You are a building code analyst. Extract all minimum room size requirements
from the following building code text.

For each requirement found, return:
- rule_id: "{jurisdiction}_{code_ref}_{section}" (e.g. "NP_NBC205_4.2")
- name: short descriptive name (e.g. "Minimum bedroom area")
- numeric_value: the minimum numeric value (number only)
- unit: "sqm" | "sqft" | "m" | "mm"
- applies_to_room_types: list of room types this applies to
- severity: "hard" (must comply) or "soft" (should comply) or "advisory"
- source_section: exact section/clause reference from the text
- confidence: 0.0–1.0 (your confidence this is a binding rule)

Text:
{chunk_text}
```

### Setback Extraction Prompt (`extract_setback_rules.md`)
```
Extract all setback / building line requirements from the following text.
Setbacks are minimum distances buildings must maintain from plot boundaries, roads,
or neighboring structures.

Return structured rules with: direction (front/rear/side/all),
condition (plot size range, road width, zone type), numeric_value, unit, source_section.
```

### Structural Extraction Prompt (`extract_structural_rules.md`)
```
Extract all structural span limits, load requirements, and material specifications.
Focus on: maximum slab span, beam depth requirements, seismic zone specifications,
and mandatory structural systems.
```

---

## Rule Versioning

Building codes change. The system handles this gracefully:

```python
class JurisdictionRuleModel(SQLModel, table=True):
    rule_id: str = Field(primary_key=True)   # "NP_NBC205_4.2"
    jurisdiction: str
    code_version: str               # "NBC_205_2012"
    effective_from: datetime
    superseded_by: Optional[str]    # rule_id of newer version when code updates
    source_doc_id: str              # BuildingCodeDocumentModel.doc_id (traceability)
    source_page: int                # PDF page the rule was extracted from
    source_section: str             # "Section 4.2, Table 4.1"
```

When a new code version is released:
1. Admin uploads new PDF → extraction → review → activate
2. Superseded rules have `superseded_by` set to the new rule_id
3. `jurisdiction/loader.py` loads rules by `code_version` — old projects unaffected
4. New projects default to the latest version per `jurisdiction/registry.py`

---

## Firm-Level Rule Overrides

If `firm.settings.custom_rules_enabled = true`, a firm_admin can override specific
rule values for projects. Use case: the local authority has approved higher density FAR.

```python
# Stored in project.properties.rule_overrides:
{
  "NP_NBC205_4.2": {
    "numeric_value": 8.0,    # Override: 8.0 sqm instead of 7.0 sqm
    "reason": "Local municipality approval for compact housing scheme",
    "approved_by": "usr_admin123",
    "approved_at": "2025-02-01"
  }
}

# Applied in jurisdiction/loader.py:
rule_set = loader.get_rule_set(
    jurisdiction="NP-KTM",
    code_version="NBC_2020_KTM",
    firm_overrides=project.properties.rule_overrides
)
```

Overrides are:
- Logged in the compliance report ("Overridden by firm — see project notes")
- Cannot reduce HARD rules below the extracted numeric_value by more than 10%

---

## ChromaDB Collections

One collection per jurisdiction group:

```python
CHROMA_COLLECTIONS = {
    "NP":    "rules_nepal",         # covers NP, NP-KTM, NP-PKR (primary MVP)
    "IN":    "rules_india",         # covers IN, IN-MH, IN-KA
    "US":    "rules_usa",           # covers US, US-CA, US-NY
    "UK":    "rules_uk",
    "CN":    "rules_china",         # covers CN, CN-SH
    "AU":    "rules_australia",
    "AE-DU": "rules_uae",
    "SG":    "rules_singapore",
}
```

### Indexing (`knowledge/indexer.py`)

```python
def index_jurisdiction(jurisdiction: str):
    collection_name = get_collection_name(jurisdiction)
    collection = chroma_client.get_or_create_collection(collection_name)

    # 1. Active rules from PostgreSQL (approved by human reviewer)
    rules = db.query(JurisdictionRuleModel).filter_by(
        jurisdiction=jurisdiction, is_active=True
    ).all()
    for rule in rules:
        collection.upsert(
            ids=[rule.rule_id],
            documents=[rule.embedding_text],
            metadatas=[{
                "rule_id": rule.rule_id,
                "category": rule.category,
                "severity": rule.severity,
                "source": rule.source_section,
                "source_doc": rule.source_doc_id,
            }]
        )

    # 2. Raw PDF text chunks from all active BuildingCodeDocuments for this jurisdiction
    docs = db.query(BuildingCodeDocumentModel).filter_by(
        jurisdiction=jurisdiction, status="active"
    ).all()
    for doc in docs:
        pdf_bytes = storage.download(doc.s3_key)
        chunks = chunk_pdf(pdf_bytes, size=500, overlap=50)
        for i, chunk in enumerate(chunks):
            collection.upsert(
                ids=[f"{doc.doc_id}_chunk_{i}"],
                documents=[chunk.text],
                metadatas=[{"doc_id": doc.doc_id, "page": chunk.page, "type": "raw_text"}]
            )
```

### Querying (`knowledge/retriever.py`)

```python
class JurisdictionAwareRetriever:

    def get_context(
        self,
        requirements: DesignRequirements,
        jurisdiction: str,
        query_context: str
    ) -> list[str]:
        collection_name = get_collection_name(jurisdiction)
        collection = self.chroma_client.get_collection(collection_name)

        query = build_query(requirements, jurisdiction, query_context)
        results = collection.query(query_texts=[query], n_results=10)
        return results["documents"][0]


def build_query(req: DesignRequirements, jurisdiction: str, context: str) -> str:
    parts = [context, req.building_type]
    if jurisdiction.startswith("NP"):
        parts.extend(["Nepal NBC", "seismic zone", "load bearing"])
    elif jurisdiction.startswith("IN"):
        parts.extend(["NBC India", "vastu" if req.vastu_compliant else ""])
    elif jurisdiction.startswith("US"):
        parts.extend(["IBC", "ADA", "egress", "zoning"])
    elif jurisdiction == "UK":
        parts.extend(["approved documents", "permitted development"])
    elif jurisdiction.startswith("CN"):
        parts.extend(["南北通透", "采光", "GB规范"])
    return " ".join(p for p in parts if p)
```

---

## Nepal-First: Initial Knowledge Base Setup (Phase 4)

Before the Nepal MVP can run designs, the following PDFs must be uploaded and extracted:

| Document | Priority | Coverage |
|----------|----------|----------|
| NBC 205:2012 (Mandatory Rules of Thumb) | Critical | Room sizes, setbacks |
| NBC 201:2012 (RC Buildings) | Critical | Structural spans, RC rules |
| NBC 105:2020 (Seismic Design) | Critical | Seismic zone V requirements |
| NBC 202:2012 (Load Bearing Masonry) | High | Masonry wall rules |
| NBCR 2072 (Building Regulations) | High | Plot coverage, FAR, setbacks |
| KMC Bylaws 2079 | High (NP-KTM) | Kathmandu-specific regulations |

Each upload goes through the full extraction → review → activate workflow.
Estimated rules per document: 10–30 rules (NBC codes are concise).

---

## Knowledge Base Rebuild Workflow

```bash
# Rebuild ChromaDB for one jurisdiction (after activating new rules)
python scripts/index_knowledge.py --jurisdiction NP-KTM

# Rebuild all jurisdictions
python scripts/index_knowledge.py --all

# Or trigger from admin UI: Settings → Knowledge Base → Rebuild Index
# Queues a Celery index_job, shows progress
```

Output:
```
Rebuilding knowledge base for NP-KTM...
  Active rules from PostgreSQL: 47 rules
  Indexing into ChromaDB collection 'rules_nepal'... done
  Loading PDF chunks from 6 active building code documents...
    NBC 205:2012 — 124 chunks
    NBC 201:2012 — 98 chunks
    NBC 105:2020 — 211 chunks
    NBC 202:2012 — 87 chunks
    NBCR 2072    — 156 chunks
    KMC Bylaws 2079 — 203 chunks
  Total indexed: 926 documents
  Collection 'rules_nepal' updated at 2025-02-18 09:15 UTC
```
