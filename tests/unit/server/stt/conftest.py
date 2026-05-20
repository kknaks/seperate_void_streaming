"""stt unit test conftest — project root 를 sys.path 앞에 삽입.

tests/unit/server/stt/ 에 __init__.py 가 없으므로 pytest 가 이 디렉토리를
standalone 테스트 디렉토리로 취급해 shadow 문제가 발생하지 않는다.
안전장치로 project root 를 명시적으로 최우선에 삽입."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).parent.parent.parent.parent.parent)

if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
elif sys.path[0] != _ROOT:
    sys.path.remove(_ROOT)
    sys.path.insert(0, _ROOT)
