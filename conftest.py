"""Root conftest — project root를 sys.path 에 추가 (server/ 패키지 임포트 지원)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
