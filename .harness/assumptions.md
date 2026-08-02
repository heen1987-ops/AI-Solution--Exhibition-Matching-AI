# Assumptions

가정은 Blocker Score 4~6점 항목에 대해서만 기록한다(7점 이상은 사용자에게 질문, 0~3점은 기록 없이 진행).

---

## ASSUMPTION-005

결정: "WAVE 0 실행 프롬프트" v2가 요구하는 `apps/api/**`(FastAPI)와 `database/migrations/**`를 새로 만들지 않는다. `backend/`(FastAPI, 8개 Alembic 마이그레이션, 94개 테스트)가 이미 그 역할을 하고 있고, 이 프롬프트 자체가 §2에서 "기존 프로젝트가 있는 경우 기존 디렉터리를 새 구조에 강제로 이동하지 않는다"고 명시한다 - §3의 apps/{api,worker,...} 구조는 "빈 저장소인 경우"의 기본값이며 이 저장소는 비어있지 않다.

근거: ASSUMPTION-001과 동일한 논리, 이번엔 프롬프트 자신의 §2 규칙으로 재확인됨. `apps/api`를 새로 만들면 `backend/`와 두 개의 병렬 FastAPI 앱이 생겨 어느 쪽이 정본인지 모호해진다.

영향: `apps/api/`는 생성하지 않음(README로 "backend/가 API 정본"이라고 리다이렉트만 남김). `database/`는 `migrations/seeds/views` 하위에 실제 SQL을 두지 않고, `backend/alembic/versions/`가 정본이라는 리다이렉트 README만 둔다(seeds는 이미 `meet-ai-ontology` CLI의 SQL 시드 생성 기능이 대체).

되돌릴 수 있는가: 그렇다.

확인 필요 시점: 실제 배포 인프라(Docker 이미지 빌드 컨텍스트) 설계 시점에 `backend/`를 `apps/api`로 옮길지 재검토(ASSUMPTION-001과 동일 시점).

## ASSUMPTION-006

결정: `apps/worker`는 정말 신규(기존에 워커가 전혀 없음)이므로 그대로 생성한다. BACKEND 트랙 소유로 배정(`locks.yaml`을 `backend/app/**`에 더해 `apps/worker/**`도 BACKEND 소유로 추가).

근거: 워커는 이번 재설계(W-6/C-7, 임베딩 재계산·알림 발송 잡)에서 처음 필요해진 신규 컴포넌트라 "기존 것을 강제 이동"하는 문제가 발생하지 않는다.

되돌릴 수 있는가: 그렇다.

확인 필요 시점: 없음(신규 컴포넌트라 충돌 위험 없음).

## ASSUMPTION-007

결정: `packages/ontology`는 Python `src/meet_ai/ontology`(온톨로지 엔진 정본)를 TS로 재구현하지 않는다 - 프런트엔드가 온톨로지 코드/유사어를 소비할 때 쓰는 얇은 TS 타입/상수 패키지로만 범위를 좁힌다(실제 판단·검증 로직은 항상 백엔드 API를 거친다).

근거: 온톨로지 판단 로직(유사어 해석, 계층 매칭)을 프런트엔드에 복제하면 "AI/판단 로직은 백엔드가 갖고 프런트는 결과만 소비한다"는 기존 원칙(ARCHITECTURE.md 핵심 설계 원칙 4·7)과 충돌한다.

되돌릴 수 있는가: 그렇다.

확인 필요 시점: CTR-003(온톨로지 계약) 완료 후 packages/ontology의 정확한 타입 목록을 확정할 때.

## ASSUMPTION-008

결정: `.harness/state.json`의 필드 형태를 이번에 받은 더 구체적인 예시에 맞춰 조정한다 - `gate_status`를 게이트별 객체가 아니라 최상위 문자열로, `next_recommended_task`(단수)를 `next_recommended_tasks`(복수 배열)로 변경한다. 게이트별 세부 판정은 정보 손실 없이 `.harness/quality-gates.yaml`(이미 게이트별 세부 criteria를 담당)에 그대로 유지한다 - state.json은 "지금 어느 게이트인지"만 한 줄로, 세부는 quality-gates.yaml이 담당하는 역할 분리로 재정리.

근거: 사용자가 state.json 형태를 두 번째로 아주 구체적인 예시와 함께 제시했다 - 더 최근·더 상세한 지시를 정본으로 채택.

되돌릴 수 있는가: 그렇다(JSON 필드명 변경일 뿐).

확인 필요 시점: 없음.

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
