# medi-new 룰

## 카테고리 enum

`planning / plan / spec / policy / adr / runbook / test / release-notes / retrospective` (ADR-0008 §1).

## slug 형식

kebab-case: `^[a-z0-9]+(-[a-z0-9]+)*$`

- ✓ `customer-onboarding`, `api-v2`, `monthly-cleanup`
- ✗ `customerOnboarding`, `Customer_Onboarding`, `api v2`

## NN 자동 카운터

해당 카테고리 디렉토리의 `<cat>-NN-*.md` 중 최대 NN + 1. 2자리 zero-padded (`01`, `02`, ..., `99`).

NN > 99 운영 시점에 3자리 확장 결정.

## D4 lineage 강제 (ADR-0008 §6)

비-`planning` 문서는 `sources:` 최소 1개 필수. medi-new 가 박는 시드는 placeholder (`[[<upstream>]]`) 들어있어 사용자가 채워야 함. 안 채우면 H1 hook (medi-validate) 가 차단.

`retrospective` 만 다수 cross-cutting (`sources:` 여러 개) 권장.

## 동작 idempotency

같은 slug 재호출 시: NN 다음 번호로 새 파일 박음 (덮어쓰기 X). 같은 slug 의 v2 가 의도면 슬러그에 명시 (`customer-onboarding-v2`).

## 보안

- slug 정규식 검증 (위 형식). 위반 시 exit 1.
- category 화이트리스트 검증. 위반 시 exit 1.
- 외부 입력은 `printf %q` 인용 또는 정규식 통과 후만 사용.
