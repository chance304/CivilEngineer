This document outlines the end-to-end vision for evolving the **AI Architectural Copilot** into a comprehensive project management and client onboarding ecosystem for civil engineering firms. It builds upon the existing 12-layer architecture to handle the full lifecycle of a building project, from initial site analysis to finalized MEP (Mechanical, Electrical, and Plumbing) documentation.

---

# Product Requirements: End-to-End Engineering Ecosystem

## 1. Project Vision & Objective

To provide a unified web portal where civil engineering firms can onboard clients, analyze sites via geo-location and CAD data, and utilize an intelligent AI design pipeline to generate fully compliant, ready-to-build documentation covering architectural, electrical, plumbing, and structural aspects.

## 2. Phase-wise User Journey

### Phase A: Client Onboarding & Site Intelligence

* **Dynamic Intake**: The firm creates a project by uploading a plot DWG/DXF and providing the geo-location.
* **Automated Rule Discovery**: Using geo-coordinates, the system queries a **Jurisdiction Registry** to identify local building codes (e.g., NBC for Nepal, DCPR for India).
* **Geospatial Analysis**: The **Plot Analyzer** extracts boundaries and orientation, while the system cross-references these with local bylaws to generate an immediate **Feasibility Report** (Max FAR, Coverage, and Setbacks).

### Phase B: Multi-Disciplinary Requirements Interview

* **The "Architectural Soul"**: A multi-turn conversational AI captures BHK needs, lifestyle preferences, and aesthetic styles.
* **The "Technical Nerves" (MEP)**: Captures detailed systems requirements:
* **Electrics**: High-load appliance placement, lighting preferences, and solar panel requirements.
* **Plumbing**: Fixture grades, solar water heating, and sanitation standards.
* **Flooring & Finishes**: Material selections (e.g., marble vs. tile) per room to refine the **Cost Estimator**.


* **Spiritual Compliance**: Vastu or other cultural spatial preferences are toggled and configured.

### Phase C: Intelligence-Driven Design Synthesis

* **Structural & Spatial Core**: The **OR-Tools CP-SAT solver** generates a valid 3D building shell, ensuring vertical continuity for staircases and columns.
* **Automated MEP Routing**:
* **Electrical Grid**: AI suggests conduit paths and switchboard locations based on the furniture layout.
* **Plumbing Stack**: Optimizes pipe runs by vertically stacking wet areas (bathrooms/kitchens) to minimize material waste and potential leaks.


* **Vastu Optimization**: A dedicated optimizer scores and adjusts the layout to maximize compliance without violating deterministic building codes.

### Phase D: Collaborative Finalization & Iteration

* **Single Source of Truth**: The portal acts as the discussion hub. Clients and senior engineers review designs via **Approval Pauses**.
* **High-Fidelity Visualization**:
* **Interactive Floor Plans**: Multi-floor SVG viewer.
* **3D Isometric Wireframes**: Real-time visualization of the building massing.


* **Version Tracking**: Every change in requirements or design is saved as a versioned **Design Session**, allowing for easy rollbacks and historical tracking.

### Phase E: Final Compliance & Handover

* **The "Final Pass"**: A comprehensive **Verification Layer** checks the finalized model against all jurisdictional rules (ventilation, area, safety).
* **Professional Documentation Set**: Generates a ZIP package containing:
* **Architectural DXF**: Detailed plans and elevations on AIA-standard layers.
* **MEP Schematic DXF**: New sheets for electrical and plumbing layouts.
* **Print-Ready PDF**: A full project report including room schedules, compliance certifications, and a tiered cost estimate.



---

## 3. System Evolution Roadmap (Actionable Steps)

| Module | Evolutionary Task | Technical Requirement |
| --- | --- | --- |
| **GIS Integration** | Link Geo-Location to `jurisdiction/registry.py` | Integrate Map API to auto-select bylaws based on coordinates. |
| **Security** | Implement Database Row-Level Security (RLS) | Secure multi-tenancy so firm data is isolated at the DB level. |
| **MEP Engine** | Expand `geometry_engine` for systems routing | Add logic to handle point-based (sockets) and line-based (pipes) entities. |
| **Structural Alignment** | Implement Vertical Column Stacking | Add solver constraints to ensure structural members align across floors. |
| **Client Role** | Full implementation of `viewer` RBAC role | Create read-only dashboard for clients to approve/reject sessions. |
| **Rule Audit** | Multi-Agent PDF Rule Verification | Use a "Checker" agent to verify extracted numeric rules against source PDFs. |

---

## 4. Final Compliance Checklist

Before any project is marked "Finalized," the system must verify:

* **Hard Rule Compliance**: 100% adherence to jurisdictional "Hard" rules.
* **Structural Integrity**: Column and staircase vertical alignment within 20mm tolerance.
* **Documentation Completeness**: Presence of all 4 elevations, site plan, and 3D wireframe.
* **Client Approval**: Digital sign-off captured in the **Design Session** history.