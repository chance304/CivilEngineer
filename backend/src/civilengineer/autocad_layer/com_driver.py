"""
AutoCAD COM bridge.

Provides a thin wrapper around win32com.client that lets the rest of the
application talk to AutoCAD without caring whether it runs on Windows or in a
CI/Linux environment.

On Windows with AutoCAD installed:
    driver = AutoCADDriver()          # connects to running AutoCAD
    doc    = driver.open_or_new()     # AcadDocument wrapper
    doc.add_line((0,0,0), (10,0,0))
    doc.save("output/floor_plan.dwg")
    driver.disconnect()

On Linux / no AutoCAD:
    driver = AutoCADDriver()          # raises AutoCADNotAvailableError
    # --- or use the DXF fallback:
    driver = AutoCADDriver(fallback_to_dxf=True)
    doc = driver.open_or_new()        # returns EzdxfDocument (ezdxf-backed)
    doc.add_line((0,0,0), (10,0,0))
    doc.save("output/floor_plan.dxf")

The fallback is used automatically in draw_node when AutoCAD is not installed,
so CI tests always pass without requiring a Windows + AutoCAD environment.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AutoCADNotAvailableError(RuntimeError):
    """Raised when win32com.client cannot connect to AutoCAD."""


class AutoCADCommandError(RuntimeError):
    """Raised when an AutoCAD COM call fails."""


# ---------------------------------------------------------------------------
# Abstract document interface
# ---------------------------------------------------------------------------


class AutoCADDocument:
    """
    Thin protocol / base class for AutoCAD document operations.
    Implemented by ComDocument (real AutoCAD) and EzdxfDocument (fallback).
    """

    def add_line(
        self,
        start: tuple[float, float, float],
        end: tuple[float, float, float],
        layer: str = "0",
    ) -> None:
        raise NotImplementedError

    def add_polyline(
        self,
        points: list[tuple[float, float, float]],
        layer: str = "0",
        closed: bool = False,
    ) -> None:
        raise NotImplementedError

    def add_text(
        self,
        text: str,
        position: tuple[float, float, float],
        height: float = 0.25,
        layer: str = "0",
    ) -> None:
        raise NotImplementedError

    def add_layer(
        self,
        name: str,
        color: int = 7,
        linetype: str = "Continuous",
    ) -> None:
        raise NotImplementedError

    def setup_standard_layers(self) -> None:
        """Create AIA-standard layers (delegates to layer_manager)."""
        from civilengineer.autocad_layer.layer_manager import setup_com_layers  # noqa: PLC0415
        setup_com_layers(self)

    def save(self, path: str | Path) -> Path:
        raise NotImplementedError

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# COM-backed document (Windows + AutoCAD required)
# ---------------------------------------------------------------------------


class ComDocument(AutoCADDocument):
    """Wraps an AcadDocument COM object."""

    def __init__(self, acad_doc: object) -> None:
        self._doc = acad_doc
        # Modelspace shortcut
        self._msp = acad_doc.ModelSpace  # type: ignore[attr-defined]

    def add_line(
        self,
        start: tuple[float, float, float],
        end: tuple[float, float, float],
        layer: str = "0",
    ) -> None:
        try:
            import win32com.client as win32  # noqa: PLC0415
            pt_s = win32.VARIANT(
                win32.pythoncom.VT_ARRAY | win32.pythoncom.VT_R8, start
            )
            pt_e = win32.VARIANT(
                win32.pythoncom.VT_ARRAY | win32.pythoncom.VT_R8, end
            )
            line = self._msp.AddLine(pt_s, pt_e)
            line.Layer = layer
        except Exception as exc:
            raise AutoCADCommandError(f"AddLine failed: {exc}") from exc

    def add_polyline(
        self,
        points: list[tuple[float, float, float]],
        layer: str = "0",
        closed: bool = False,
    ) -> None:
        try:
            import win32com.client as win32  # noqa: PLC0415
            flat = [v for pt in points for v in pt]
            pts = win32.VARIANT(
                win32.pythoncom.VT_ARRAY | win32.pythoncom.VT_R8, flat
            )
            pline = self._msp.Add3DPoly(pts)
            pline.Layer = layer
            if closed:
                pline.Closed = True
        except Exception as exc:
            raise AutoCADCommandError(f"Add3DPoly failed: {exc}") from exc

    def add_text(
        self,
        text: str,
        position: tuple[float, float, float],
        height: float = 0.25,
        layer: str = "0",
    ) -> None:
        try:
            import win32com.client as win32  # noqa: PLC0415
            pt = win32.VARIANT(
                win32.pythoncom.VT_ARRAY | win32.pythoncom.VT_R8, position
            )
            txt = self._msp.AddText(text, pt, height)
            txt.Layer = layer
        except Exception as exc:
            raise AutoCADCommandError(f"AddText failed: {exc}") from exc

    def add_layer(
        self,
        name: str,
        color: int = 7,
        linetype: str = "Continuous",
    ) -> None:
        try:
            layers = self._doc.Layers
            if name not in [layers.Item(i).Name for i in range(layers.Count)]:
                layer = layers.Add(name)
            else:
                layer = layers.Item(name)
            layer.color = color
        except Exception as exc:
            raise AutoCADCommandError(f"Layer.Add failed: {exc}") from exc

    def save(self, path: str | Path) -> Path:
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._doc.SaveAs(str(path))
            logger.info("Saved AutoCAD drawing to %s", path)
            return path
        except Exception as exc:
            raise AutoCADCommandError(f"SaveAs failed: {exc}") from exc

    def close(self) -> None:
        try:
            self._doc.Close(False)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# ezdxf-backed document (Linux / no AutoCAD fallback)
# ---------------------------------------------------------------------------


class EzdxfDocument(AutoCADDocument):
    """
    Drop-in replacement for ComDocument backed by ezdxf.

    Accepts the same add_* calls and saves to DXF instead of DWG.
    """

    def __init__(self) -> None:
        import ezdxf  # noqa: PLC0415
        self._doc = ezdxf.new("R2010")
        self._doc.header["$INSUNITS"] = 6  # metres
        self._doc.header["$MEASUREMENT"] = 1  # metric
        self._msp = self._doc.modelspace()

    def add_line(
        self,
        start: tuple[float, float, float],
        end: tuple[float, float, float],
        layer: str = "0",
    ) -> None:
        self._msp.add_line(start[:2], end[:2], dxfattribs={"layer": layer})

    def add_polyline(
        self,
        points: list[tuple[float, float, float]],
        layer: str = "0",
        closed: bool = False,
    ) -> None:
        pts2d = [(p[0], p[1]) for p in points]
        pline = self._msp.add_lwpolyline(pts2d, dxfattribs={"layer": layer})
        pline.closed = closed

    def add_text(
        self,
        text: str,
        position: tuple[float, float, float],
        height: float = 0.25,
        layer: str = "0",
    ) -> None:
        self._msp.add_text(
            text,
            dxfattribs={
                "insert": (position[0], position[1]),
                "height": height,
                "layer": layer,
            },
        )

    def add_layer(
        self,
        name: str,
        color: int = 7,
        linetype: str = "Continuous",
    ) -> None:
        if name not in self._doc.layers:
            layer = self._doc.layers.new(name)
        else:
            layer = self._doc.layers.get(name)
        layer.color = color

    def save(self, path: str | Path) -> Path:
        path = Path(path).resolve()
        # Always save as DXF regardless of extension
        if path.suffix.lower() == ".dwg":
            path = path.with_suffix(".dxf")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._doc.saveas(str(path))
        logger.info("Saved ezdxf DXF to %s (AutoCAD fallback)", path)
        return path

    @property
    def ezdxf_doc(self):
        """Access the underlying ezdxf document for advanced use."""
        return self._doc


# ---------------------------------------------------------------------------
# AutoCAD driver (connects to running AutoCAD or returns DXF fallback)
# ---------------------------------------------------------------------------


class AutoCADDriver:
    """
    Factory for AutoCAD document objects.

    Args:
        fallback_to_dxf: If True, return an EzdxfDocument when AutoCAD
                         is not available instead of raising an error.
    """

    def __init__(self, fallback_to_dxf: bool = True) -> None:
        self._fallback = fallback_to_dxf
        self._app: object | None = None

    def connect(self) -> None:
        """
        Attempt to connect to a running AutoCAD instance via COM.
        Raises AutoCADNotAvailableError if unavailable and fallback=False.
        """
        try:
            import win32com.client as win32  # noqa: PLC0415
            self._app = win32.GetActiveObject("AutoCAD.Application")
            logger.info("Connected to AutoCAD via COM")
        except ImportError:
            if not self._fallback:
                raise AutoCADNotAvailableError(
                    "win32com not installed — AutoCAD COM bridge requires Windows."
                )
            logger.info("win32com not available; DXF fallback will be used.")
        except Exception as exc:
            if not self._fallback:
                raise AutoCADNotAvailableError(
                    f"Could not connect to AutoCAD: {exc}"
                ) from exc
            logger.info("AutoCAD not running; DXF fallback will be used.")

    def open_or_new(self, dwg_path: str | Path | None = None) -> AutoCADDocument:
        """
        Return an AutoCADDocument.

        If AutoCAD is available: opens dwg_path (or creates a new drawing).
        Otherwise: returns an EzdxfDocument.
        """
        if self._app is not None:
            try:
                docs = self._app.Documents  # type: ignore[attr-defined]
                if dwg_path:
                    doc = docs.Open(str(Path(dwg_path).resolve()))
                else:
                    doc = docs.Add()
                return ComDocument(doc)
            except Exception as exc:
                if not self._fallback:
                    raise AutoCADCommandError(
                        f"Failed to open/create AutoCAD document: {exc}"
                    ) from exc
                logger.warning("AutoCAD document open failed; falling back to ezdxf.")

        # Fallback
        return EzdxfDocument()

    def disconnect(self) -> None:
        """Release COM connection (no-op if not connected)."""
        self._app = None
        logger.debug("AutoCAD driver disconnected.")

    @staticmethod
    def is_available() -> bool:
        """Return True if win32com is importable and AutoCAD is running."""
        try:
            import win32com.client as win32  # noqa: PLC0415
            win32.GetActiveObject("AutoCAD.Application")
            return True
        except Exception:
            return False
