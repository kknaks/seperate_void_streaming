"""PgvectorStore live 통합 테스트 — spec-05 §5.3 storage/ PR 자동 게이트.

실 PostgreSQL + pgvector 인스턴스 필요. 별도 task 발주 시 구현.
현재는 placeholder — pytest collection 시 skip 처리.
"""

import pytest

pytestmark = pytest.mark.skip(reason="live category — requires PostgreSQL + pgvector instance")


def test_placeholder() -> None:
    pass
