# medi-version-cut 룰

## 라벨 형식

영숫자 + `. _ -` 만 (정규식 `^[a-zA-Z0-9._-]+$`).

| 컨벤션 | 예 | 적합 |
|--------|----|----|
| semver | `v1.0`, `v1.1`, `v2.0` | 제품·라이브러리 |
| 분기 | `2026Q2`, `2026Q3` | 정책·계획 중심 |
| 릴리즈 | `release-2026-04`, `release-2026-05` | 일자 기반 운영 |

## 사전 조건

- `medi_docs/current/` 존재 필수.
- 이미 동일 라벨 존재 (`medi_docs/<label>/`) 시 차단 — 다른 라벨 사용.

## 박제 범위 (ADR-0008 §3)

- `current/` 전체 → `v{label}/` 으로 복사.
- `_map.md` 도 박제 (관계 그래프 동결).
- read-only 마크 (`chmod -R a-w`).

## 사전 검증 (D1 강제)

cut 직전 docs-validate (medi-validate.sh) 통과 필수. 실패 시 박제 차단.

위반 패턴:
- frontmatter 누락 → 차단
- 비-planning 문서 `sources:` 누락 (D4) → 차단

## R4 동기화 (ADR-0006 D-4)

cut 사전 단계에 `medi-claude-md-augment.sh` 자동 실행 → CLAUDE.md 마커 블록 재합성. cut 시점 plugin 풍경 (현재 설치된 SKILL/슬래시 목록) 동결.

R4 실패 시 cut 차단 (D-4 wiring).

## carry-forward (ADR-0008 §2)

cut 후 `current/` 그대로 유지. cut = *박제 + 계속 작업* (둘 동시).

## D2 — `v{label}/` 불변

박제된 `v{label}/` 는 cut 이후 수정 X (read-only 마크). 변경 필요 시 새 cut. 사용자가 강제로 chmod 풀고 수정 시 메인테이너 자기 책임.

## 보안

- 라벨 정규식 검증. 위반 시 exit 1.
- `cp -R` + `chmod` 만 — destructive 동작 X (`rm` 없음).
- cut 실패 시 부분 박제 정리는 사용자 손 (자동 rollback 안 함, 운영 후 도입 검토).
