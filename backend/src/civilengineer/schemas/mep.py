"""
MEP (Mechanical, Electrical, Plumbing) schemas.

All spatial coordinates are in metres.
Pipe diameters are in millimetres.
Wire gauges are in mm².
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MEPPoint(BaseModel):
    """A 3D point in the MEP routing network."""

    x: float        # metres from buildable zone origin
    y: float        # metres from buildable zone origin
    floor: int      # 1-indexed floor number


class ConduitRun(BaseModel):
    """A single electrical conduit run from panel to room outlets."""

    run_id: str
    circuit_name: str           # e.g. "LIGHTING_F1", "POWER_KITCHEN"
    path: list[MEPPoint]        # waypoints through ceiling/walls
    wire_gauge_mm2: float       # 2.5 lighting, 6.0 power, 10.0 AC
    conduit_dia_mm: float       # outer conduit diameter
    load_kva: float = 0.0       # estimated load for this circuit


class PlumbingStack(BaseModel):
    """A vertical plumbing stack connecting wet rooms on multiple floors."""

    stack_id: str
    wet_rooms: list[str]            # room_ids sharing this vertical stack
    cold_pipe_path: list[MEPPoint]  # cold water supply route
    hot_pipe_path: list[MEPPoint]   # hot water supply route
    pipe_dia_mm: float              # nominal pipe diameter (mm)
    floors_served: list[int] = Field(default_factory=list)


class ElectricalPanel(BaseModel):
    """Distribution board / consumer unit location and sizing."""

    panel_id: str
    location: MEPPoint
    num_circuits: int
    load_kva: float
    phase: Literal["1-phase", "3-phase"] = "1-phase"


class MEPNetwork(BaseModel):
    """Complete MEP routing network for the whole building."""

    conduit_runs: list[ConduitRun] = Field(default_factory=list)
    plumbing_stacks: list[PlumbingStack] = Field(default_factory=list)
    panels: list[ElectricalPanel] = Field(default_factory=list)
    total_electrical_load_kva: float = 0.0
    total_pipe_run_m: float = 0.0


# ---------------------------------------------------------------------------
# MEP design requirements (from interview)
# ---------------------------------------------------------------------------


class MEPRequirements(BaseModel):
    """MEP-specific design requirements collected during the interview."""

    high_load_appliances: list[str] = Field(default_factory=list)
    # e.g. ["AC_MASTER", "WM_UTILITY", "WATER_HEATER_BATH1"]

    solar_pv: bool = False
    solar_pv_kw: float | None = None        # target PV capacity
    solar_water_heating: bool = False
    plumbing_grade: Literal["basic", "standard", "premium"] = "standard"
    lighting_preference: Literal["natural-first", "task", "feature"] = "natural-first"
