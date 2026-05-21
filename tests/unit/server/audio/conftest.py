"""audio unit test conftest — project root 를 sys.path 앞에 삽입."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).parent.parent.parent.parent.parent)

if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
elif sys.path[0] != _ROOT:
    sys.path.remove(_ROOT)
    sys.path.insert(0, _ROOT)
