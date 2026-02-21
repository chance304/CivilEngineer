"""
Root conftest — adds src/ to sys.path so tests can import civilengineer
without installing the full package (avoids pulling in heavy deps like torch).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
