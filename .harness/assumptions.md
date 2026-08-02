# Assumptions

가정은 Blocker Score 4~6점 항목에 대해서만 기록한다(7점 이상은 사용자에게 질문, 0~3점은 기록 없이 진행).

---

## ASSUMPTION-001

결정: 기존 `backend/`(FastAPI, SQLAlchemy, Alembic)와 `src/meet_ai/`(온톨로지·스코어링 코어)를 메타프롬프트가 예시로 든 `apps/api`, `apps/worker` 경로로 물리 이동하지 않는다. 대신 `apps/`, `packages/`는 지금부터 생성되는 신규 코드(Next.js 프런트엔드 3종, 신규 공유 TS 패키지)의 위치로만 사용한다.

근거: 이동 자체는 git으로 되돌릴 수 있지만, `backend/alembic`의 상대경로 참조, `pyproject.toml`(루트)과 `backend/pyproject.toml` 두 개의 분리된 패키지 정의, 8개 기존 마이그레이션, 94개(83 유닛+11 통합) 기존 테스트가 전부 경로에 의존한다. 물리 이동은 검증 범위가 이 항목 하나로 끝나지 않고 전체 회귀시험을 요구하므로, 이번 하네스 부트스트랩 시점에 처리하기에는 위험 대비 이득이 낮다.

영향: `locks.yaml`의 BACKEND/CONTRACTS/AI_SEARCH 트랙이 소유하는 경로가 메타프롬프트 원문 예시(`apps/api/**`, `apps/worker/**`)와 다르게 `backend/**`, `src/meet_ai/**` 하위로 매핑된다.

되돌릴 수 있는가: 그렇다 - 필요 시 이후 Wave에서 별도 `CHANGE_REQUEST`로 물리 이동을 재추진할 수 있다.

확인 필요 시점: Wave 2 시작 전, 실제 배포 파이프라인(Docker 이미지 빌드 컨텍스트)을 설계할 때 이 구조가 여전히 적합한지 재확인.

---

## ASSUMPTION-002

결정: G0_BOOTSTRAP의 "모든 앱이 로컬에서 실행" 기준은 이번 부트스트랩 시점에는 `apps/user-web`/`apps/kiosk`/`apps/admin`이 아직 존재하지 않으므로 충족 불가능한 것으로 간주하고, G0을 "BACKEND+인프라 한정 부분 통과"로 취급한다. 프런트엔드 앱이 생기는 Wave 1(WEB-001/KSK-001/ADM-001) 완료 시점에 G0을 재검사한다.

근거: 메타프롬프트 자체가 Wave 1에서 "USER EXPERIENCE SKELETON"(라우트 뼈대 생성)을 정의하고 있어, 그 전까지 앱이 없는 것은 설계된 순서이지 결함이 아니다.

영향: `state.json.gate_status.G0_BOOTSTRAP = "IN_PROGRESS"`(FAILED 아님)로 표기.

되돌릴 수 있는가: 그렇다 - 판단 기준일 뿐 코드·스키마에 영향 없음.

확인 필요 시점: WEB-001/KSK-001/ADM-001 완료 직후.

---

## ASSUMPTION-003

결정: Wave 2·Wave 3 백로그는 이번 부트스트랩에서 세부 2시간 단위까지 전개하지 않고, 트랙별 기능 그룹(`BAC-GROUP-001` 등, status: `PENDING_DECOMPOSITION`) 수준으로만 기록한다. 각 Wave 시작 시점에 그 Wave만 세부 태스크로 분해한다.

근거: Wave 0/1의 실제 산출물(계약 확정 결과, 프런트엔드 뼈대 구조)이 Wave 2 작업의 정확한 파일 경계를 바꿀 수 있어, 지금 세부 분해하면 상당 부분 재작업된다. "2시간 이내 단위로 분해"라는 요구 자체는 각 Wave 착수 시점에 그 Wave에 대해 지키면 충족된다.

영향: `backlog.yaml`에 `PENDING_DECOMPOSITION` 상태의 굵은 항목이 존재 - `다음` 명령이 Wave 2에 도달하면 그 항목을 먼저 세부 분해하는 작업으로 처리한다.

되돌릴 수 있는가: 그렇다.

확인 필요 시점: Wave 1의 G1_CONTRACT_FREEZE 통과 시점(Wave 2 착수 직전).

---

## ASSUMPTION-004

결정: `README.md`·`AGENTS.md`(기존본)가 참조하던 "ChatGPT 공유 스레드를 설계 기준선으로 우선 검토하라"는 구 지시는 이번 메타프롬프트가 정의한 `docs/redesign-v2/00-master-spec-v1.md`(v1.0 통합 개발 명세서)로 대체된 것으로 간주한다 - 새 `AGENTS.md`는 v1.0 명세서를 단일 기준으로 명시하고, 외부 ChatGPT 스레드 참조는 제거한다.

근거: v1.0 명세서 자체가 "본 문서를 개발의 단일 기준으로 사용한다"고 명시했고, 사용자가 이전 턴에서 "기존 백엔드를 이 새 스펙에 맞게 재설계 시작"이라고 명시적으로 확인했다.

영향: 새 `AGENTS.md`에는 외부 URL 기준선 대신 `docs/redesign-v2/` 문서 체계가 필수 참조로 명시된다.

되돌릴 수 있는가: 그렇다 - 문서 텍스트 변경일 뿐.

확인 필요 시점: 즉시 확인 가능하면 좋으나 차단 사유는 아님(기존 지시와 신규 지시가 상충하지 않고 대체 관계이므로 4~6점 항목으로 처리).
