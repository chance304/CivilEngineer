"""
ODA File Converter wrapper: converts DXF → DWG.

The ODA File Converter is a free CLI tool from the Open Design Alliance.
It must be installed at /opt/oda/ODAFileConverter (default) or the path
must be set via the ODA_CONVERTER_PATH environment variable.

Docker setup (add to worker Dockerfile):
    RUN apt-get install -y libqt5core5a libqt5gui5 libqt5widgets5 \\
        && wget -q https://download.opendesign.com/guestfiles/ODAFileConverter/\\
           ODAFileConverter_QT5_lnxX64_8_21dll.tar.gz -O /tmp/oda.tar.gz \\
        && mkdir -p /opt/oda \\
        && tar -xzf /tmp/oda.tar.gz -C /opt/oda/ \\
        && rm /tmp/oda.tar.gz
    ENV ODA_CONVERTER_PATH=/opt/oda/ODAFileConverter

ODA CLI syntax:
    ODAFileConverter <in_dir> <out_dir> <version> <format> <recurse> <audit> [filter]
    version: ACAD2018 (or ACAD2000, ACAD2004, ACAD2007, ACAD2010, ACAD2013)
    format:  DWG or DXF
    recurse: 0 = no subdirs, 1 = recurse
    audit:   0 = no audit, 1 = audit and fix

Usage:
    from civilengineer.cad_layer.oda_converter import convert_to_dwg
    dwg_path = convert_to_dwg(Path("output/session/floor_1.dxf"))
    if dwg_path:
        print("DWG written to", dwg_path)
    else:
        print("ODA converter unavailable; DXF kept as-is.")
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_ODA_ENV_VAR = "ODA_CONVERTER_PATH"
_ODA_DEFAULT  = "/opt/oda/ODAFileConverter"
_TIMEOUT_S    = 30  # seconds per file

# Target DWG version — ACAD2018 is widely compatible
_DWG_VERSION = "ACAD2018"


def _find_oda_binary() -> str | None:
    """
    Locate the ODA File Converter binary.

    Search order:
    1. ODA_CONVERTER_PATH environment variable
    2. Default path /opt/oda/ODAFileConverter
    3. System PATH (shutil.which)
    """
    # Environment variable override
    candidate = os.environ.get(_ODA_ENV_VAR, _ODA_DEFAULT)
    if Path(candidate).is_file():
        return candidate
    found = shutil.which(candidate)
    if found:
        return found

    # System PATH fallback
    found = shutil.which("ODAFileConverter")
    if found:
        return found

    return None


def convert_to_dwg(dxf_path: Path) -> Path | None:
    """
    Convert a single DXF file to DWG using ODA File Converter.

    Args:
        dxf_path : absolute path to the source .dxf file

    Returns:
        Path to the output .dwg file on success, None if conversion fails
        or ODA binary is unavailable.
    """
    oda = _find_oda_binary()
    if oda is None:
        logger.debug(
            "ODA File Converter not found; skipping DWG conversion. "
            "Set ODA_CONVERTER_PATH or install to /opt/oda/ODAFileConverter."
        )
        return None

    if not dxf_path.exists():
        logger.warning("convert_to_dwg: source file not found: %s", dxf_path)
        return None

    out_dir = dxf_path.parent / "dwg"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ODA syntax: <in_dir> <out_dir> <version> DWG <recurse=0> <audit=1> [filter]
    cmd = [
        oda,
        str(dxf_path.parent),   # input directory
        str(out_dir),            # output directory
        _DWG_VERSION,            # DWG version
        "DWG",                   # output format
        "0",                     # no recursion
        "1",                     # audit + fix
        dxf_path.name,           # file filter (only this file)
    ]

    try:
        result = subprocess.run(
            cmd,
            check=False,
            timeout=_TIMEOUT_S,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning(
                "ODA converter returned code %d for %s: %s",
                result.returncode, dxf_path.name, result.stderr[:200],
            )

        expected_dwg = out_dir / dxf_path.with_suffix(".dwg").name
        if expected_dwg.exists():
            logger.info("DWG conversion: %s → %s", dxf_path.name, expected_dwg)
            return expected_dwg

        logger.warning(
            "ODA converter ran but DWG not found at %s", expected_dwg
        )
        return None

    except subprocess.TimeoutExpired:
        logger.warning("ODA converter timed out after %ds for %s", _TIMEOUT_S, dxf_path.name)
        return None
    except FileNotFoundError:
        logger.warning("ODA converter binary not executable: %s", oda)
        return None
    except OSError as exc:
        logger.warning("ODA converter OS error for %s: %s", dxf_path.name, exc)
        return None
