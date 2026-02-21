"""
Core design schemas.

All spatial values are in metres.
All areas are in square metres.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


class Point2D(BaseModel):
    x: float  # metres from plot origin
    y: float  # metres from plot origin


class Rect2D(BaseModel):
    """Axis-aligned rectangle defined by its lower-left corner plus dimensions."""

    x: float  # metres — lower-left X
    y: float  # metres — lower-left Y
    width: float  # metres
    depth: float  # metres

    @property
    def area(self) -> float:
        return self.width * self.depth

    @property
    def center(self) -> Point2D:
        return Point2D(x=self.x + self.width / 2, y=self.y + self.depth / 2)


# ---------------------------------------------------------------------------
# Room types
# ---------------------------------------------------------------------------


class RoomType(StrEnum):
    MASTER_BEDROOM = "master_bedroom"
    BEDROOM = "bedroom"
    LIVING_ROOM = "living_room"
    DINING_ROOM = "dining_room"
    KITCHEN = "kitchen"
    BATHROOM = "bathroom"
    TOILET = "toilet"
    STAIRCASE = "staircase"
    CORRIDOR = "corridor"
    GARAGE = "garage"
    STORE = "store"
    POOJA_ROOM = "pooja_room"
    HOME_OFFICE = "home_office"
    BALCONY = "balcony"
    TERRACE = "terrace"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Door / window / wall
# ---------------------------------------------------------------------------


class WallFace(StrEnum):
    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"


class DoorSwing(StrEnum):
    LEFT = "left"
    RIGHT = "right"


class Door(BaseModel):
    wall_face: WallFace
    position_along_wall: float  # metres from left edge of that wall
    width: float = 0.9          # metres (standard single-leaf)
    swing: DoorSwing = DoorSwing.LEFT
    is_main_entrance: bool = False


class Window(BaseModel):
    wall_face: WallFace
    position_along_wall: float  # metres from left edge of that wall
    width: float = 1.2          # metres
    height: float = 1.2         # metres
    sill_height: float = 0.9    # metres from floor


class WallSegment(BaseModel):
    """An individual wall segment (not a room outline wall)."""

    start: Point2D
    end: Point2D
    thickness: float = 0.23   # metres (230mm — standard 9" brick)
    is_load_bearing: bool = True
    is_external: bool = False


# ---------------------------------------------------------------------------
# Room layout
# ---------------------------------------------------------------------------


class RoomLayout(BaseModel):
    room_id: str
    room_type: RoomType
    name: str                        # Display label, e.g. "Master Bedroom"
    floor: int = 1                   # 1-indexed floor number
    bounds: Rect2D                   # Position within the buildable zone
    doors: list[Door] = Field(default_factory=list)
    windows: list[Window] = Field(default_factory=list)
    is_external_wall_north: bool = False
    is_external_wall_south: bool = False
    is_external_wall_east: bool = False
    is_external_wall_west: bool = False

    @property
    def area(self) -> float:
        return self.bounds.area


# ---------------------------------------------------------------------------
# Floor plan
# ---------------------------------------------------------------------------


class FloorPlan(BaseModel):
    """Layout for a single floor."""

    floor: int                       # 1-indexed
    floor_height: float = 3.0        # metres (floor-to-ceiling)
    buildable_zone: Rect2D           # Available zone after setbacks
    rooms: list[RoomLayout] = Field(default_factory=list)
    wall_segments: list[WallSegment] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Full multi-floor building design
# ---------------------------------------------------------------------------


class BuildingDesign(BaseModel):
    """Complete multi-floor building design — output of the geometry engine."""

    design_id: str
    project_id: str
    jurisdiction: str = "NP-KTM"
    num_floors: int
    plot_width: float     # metres
    plot_depth: float     # metres
    north_direction_deg: float = 0.0  # 0 = drawing top is north
    floor_plans: list[FloorPlan] = Field(default_factory=list)

    # Setbacks applied (metres)
    setback_front: float = 3.0
    setback_rear: float = 1.5
    setback_left: float = 1.5
    setback_right: float = 1.5


# ---------------------------------------------------------------------------
# Design requirements (from interview — used by solver)
# ---------------------------------------------------------------------------


class RoomRequirement(BaseModel):
    room_type: RoomType
    floor: int | None = None      # None = solver decides
    min_area: float | None = None # sqm — override jurisdiction minimum
    name: str | None = None


class StylePreference(StrEnum):
    MODERN = "modern"
    TRADITIONAL = "traditional"
    MINIMAL = "minimal"
    NEWARI = "newari"
    CLASSICAL = "classical"


class DesignRequirements(BaseModel):
    project_id: str
    jurisdiction: str = "NP-KTM"
    num_floors: int = 2
    rooms: list[RoomRequirement] = Field(default_factory=list)
    style: StylePreference = StylePreference.MODERN
    vastu_compliant: bool = False
    seismic_zone: str = "V"           # Nepal default
    road_width_m: float | None = None   # Used to compute setbacks in Nepal
    notes: str = ""
