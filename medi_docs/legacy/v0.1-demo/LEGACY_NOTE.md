# v0.1-demo legacy

이 디렉토리는 PLAN-001~006 (V-01 closed + V-04~V-06 데모 시리즈) 전체 폐기 시점의 snapshot.

폐기 결정 (2026-05-22): wrapper (speaker_engine) 의 실증 효과 미미 검증 (admin smoke v6~v11). 프로젝트 정체성을 "ablation study + 단순 demo" 로 reframe.

보존 자산:
- adr-01~10
- spec-01~08
- plan/PLAN-001~006
- planning/planning-01~03
- _map.md

폐기 사유:
- speaker_engine 의 OnlineSpeakerClusterer / AdaptiveScheduler / FinalReclusterer / identify_phrase 의 실증 효과 미미 (admin smoke 측정)
- PLAN-006 STT-driven chain 의 본질 한계 (phrase-level embedding ≠ speaker discrimination at conversational durations)
- 새 방향: diart + ECAPA-TDNN (또는 다른) embedding + ElevenLabs STT + 시간감쇠 scheduler — ablation 으로 최적 조합 도출

이후 변경 (코드 폐기/재작성/유지) 은 v0.2 plan 에서 결정.
