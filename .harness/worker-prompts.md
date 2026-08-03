# Worker Prompt Pack v1.0

사용자가 전달한 "병렬 워커 실행 프롬프트 팩 v1.0" 원문을 저장한다. 오케스트레이터(나)가 `다음`/`다음 3` 처리 시 트랙별 워커(Agent 도구)를 기동할 때 이 문서의 역할 정의를 그대로 사용한다. 컨텍스트가 초기화돼도 이 파일만으로 워커 디스패치 방식을 복구한다.

## 경로 이름 재매핑 (중요)

이 프롬프트 팩은 이상적 경로(`apps/api`, `apps/worker`, `database/migrations`, `packages/ontology`, `ai/`)를 전제하지만, 이 저장소는 `.harness/assumptions.md` ASSUMPTION-001에 따라 다음과 같이 실제 경로로 재매핑한다 - 워커를 기동할 때 아래 표를 프롬프트에 함께 주입한다.

| 프롬프트 팩 원문 경로 | 실제 저장소 경로 |
| --- | --- |
| `apps/api/**`, `apps/worker/**` (BACKEND) | `backend/app/api/**`, `backend/app/core/**`, `backend/app/main.py`, `backend/scripts/**` |
| `database/migrations/**` (CONTRACTS) | `backend/alembic/versions/**`, `backend/app/models/**`, `db/migrations/**`(레거시, 정본 아님) |
| `packages/ontology/**` (CONTRACTS) | `src/meet_ai/ontology/**`(온톨로지 카탈로그 정본), `.harness/contracts/ontology.yaml`(계약 요약) |
| `ai/**` (AI_SEARCH) | `backend/app/services/matching/**`, `src/meet_ai/scoring/**`, `netlify/functions/**` |
| `packages/shared-types/**` 등 신규 TS 패키지 | `packages/*/`(아직 대부분 미생성) |
| `apps/user-web/**`, `apps/kiosk/**`, `apps/admin/**` | 동일(그대로 사용, 아직 미생성) |

전체 소유권 정본은 여전히 `.harness/locks.yaml`이다 - 이 표는 프롬프트 팩 문구를 그대로 워커에 복사할 때 헷갈리지 않기 위한 변환표일 뿐이다.

---

(이하 사용자가 제공한 원문 A~L 섹션 - 공통 워커 프롬프트, CONTRACTS/BACKEND/USER_WEB/KIOSK/ADMIN/AI_SEARCH/QA_SECURITY 워커 프롬프트, 통합 작업 프롬프트, 병렬 실행 요청 형식(J), Change Request 형식(K), `다음` 실행 예시(L). 원문 전체는 이 세션의 대화 기록 참고 - 요약하지 않고 그대로 적용한다.)

핵심 요지만 발췌:

- 모든 워커는 시작 전 AGENTS.md → PROJECT_SCOPE.md → state.json → backlog.yaml → locks.yaml → contracts/** → 관련 handoffs를 읽는다.
- 워커 실행 루프: INSPECT → TASK PLAN → IMPLEMENT → TEST → SELF REVIEW → HANDOFF.
- 완료 응답은 `TASK/STATUS/IMPLEMENTED/TESTED/FILES/CONTRACT IMPACT/RISKS/HANDOFF/NEXT DEPENDENCY` 형식.
- 공유 계약 변경은 코드로 우회하지 않고 `.harness/handoffs/contracts/change-request-{id}.md`(K 형식)를 생성, 승인 전에는 계약을 수정하지 않는다.
- 오케스트레이터의 작업 전달 형식은 J(task_id/track/title/objective/depends_on/owned_paths/inputs/acceptance/tests/prohibited) YAML을 따른다 - `.harness/backlog.yaml`의 각 태스크 필드와 1:1 대응하도록 다음부터 태스크 전달 시 이 필드들을 채워 Agent 프롬프트에 주입한다.
- QA_SECURITY 워커의 판정은 `PASS`/`PASS_WITH_WARNING`/`FAIL`/`BLOCK_RELEASE` 4단계.

## 적용 방식 (이 저장소에서 구체적으로 어떻게 쓰는가)

Wave 0(FOUNDATION)처럼 단일 소유·순차 설정 작업은 오케스트레이터가 직접 구현한다(워커 기동 불필요). Wave 1부터 트랙이 실제로 분기하는 시점부터 트랙별 Agent를 병렬 기동한다 - 각 Agent 프롬프트는 이 문서의 해당 트랙 섹션(B~H) + 위 경로 재매핑표 + `.harness/backlog.yaml`의 해당 태스크 필드(J 형식)를 결합해 구성한다.
