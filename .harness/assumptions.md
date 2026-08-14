# Assumptions

Decisions made without asking the user, per the Blocker Score rule in
[docs/harness-orchestrator-prompt-pack.md](../docs/harness-orchestrator-prompt-pack.md) §5.

---

## ASSUMPTION-001 — SUPERSEDED by DECISION-006 (2026-08-02)

> 사용자가 명시적으로 pnpm+apps/* 정식 모노레포 전환을 지시해 `backend/`→`apps/api`,
> `frontend/`→`apps/user-web` 물리 이동을 완료했다. 아래는 그 이전의 원래 판단 기록(보존).

**결정**: `apps/api`, `apps/user-web`를 새로 만들어 기존 `backend/`, `frontend/`를 이관하지 않는다.
대신 `locks.yaml`에서 BACKEND 트랙이 `backend/**`를, USER_WEB 트랙이 `frontend/**`를 소유하는
것으로 기록하고, 새 트랙(KIOSK/ADMIN/AI_SEARCH 공식·CONTRACTS 공식)만 canonical한 `apps/*`,
`packages/*`, `ai/*` 경로에 새로 만든다.

**근거**: `backend/`는 이미 48개 API 엔드포인트가 OpenAPI 스키마로 정상 생성되고 15단계
Alembic 마이그레이션(86 테이블)이 SQL로 컴파일 검증된 상태였고, `frontend/`는 이미
`npm run build`가 20개 라우트로 성공한 상태였다(2026-08-02). 대규모 물리적 디렉터리 이동은
(1) Python 패키지 경로(`app.*`)와 SQLAlchemy 메타데이터/Alembic 리비전 체인을 깨뜨릴 위험이 크고,
(2) 검증된 빌드 상태를 다시 검증해야 하는 비용이 크며, (3) 이미 여러 동시 실행 에이전트가
`backend/app/**` 경로를 참조해 작업 중이었다.

**영향**: `.harness/locks.yaml`과 `AGENTS.md`에 경로 매핑을 명시했다. KIOSK/ADMIN 워커가
`apps/kiosk/**`, `apps/admin/**`를 canonical하게 새로 만들면, 결과적으로 저장소는 당분간
`backend/`+`frontend/`(레거시 이름) + `apps/kiosk/`+`apps/admin/`(신규 이름)이 공존하는
비대칭 구조가 된다.

**되돌릴 수 있는가**: 예 — 언제든 `git mv backend apps/api && git mv frontend apps/user-web` +
import 경로 일괄 치환으로 정리 가능. 되돌리는 비용은 중간 정도(자동화 스크립트로 대부분 처리 가능).

**확인 필요 시점**: KIOSK/ADMIN 트랙이 기본 골격을 갖춘 뒤, 또는 사용자가 명시적으로
디렉터리명 통일을 요청할 때.

---

## ASSUMPTION-002

**결정**: 재설계(웹/키오스크 분리) 이전에 만들어진 `backend/`+`frontend/`의 도메인 모델·API를
"파기하고 새로 만들지" 않고 "그대로 유지하며 재설계 문서와의 차이만 CONTRACT-003에서 조정"하는
쪽으로 진행한다.

**근거**: 기존 구현이 재설계 문서(§38 핵심 데이터모델, §40 API)보다 오히려 더 상세하고
(온톨로지 복합키 참조, provenance/신뢰도/버전관리 등 AGENTS.md의 불변조건을 이미 반영) 실제
빌드·마이그레이션 검증까지 끝난 상태였다. 재설계 문서 쪽이 초안 수준의 단순화된 버전으로 보인다.

**영향**: 일부 API 경로 명명(예: `/api/v1/me/event-profile` vs 기존 `/api/v1/profiles/me`)이
재설계 문서와 다를 수 있다. CONTRACT-003에서 각 불일치를 개별 판단한다.

**되돌릴 수 있는가**: 예, 하지만 재작업 비용이 있어 Blocker Score 4~6점 구간으로 판단해
기본값(기존 유지)을 적용하고 여기 기록한다. 사용자가 재설계 문서 쪽 경로를 그대로 강제하길
원하면 CONTRACT-003에서 뒤집을 수 있다.

**확인 필요 시점**: CONTRACT-003 작업 시.

---

## ASSUMPTION-003 (2026-08-02) — WAVE 2C/2D/2E 경로 규칙을 기존 구조에 매핑

**결정**: 외부(Codex) 프롬프트가 지정한 `apps/api/src/modules/<domain>/**`,
`apps/worker/src/jobs/<job>/**` 같은 신규 모듈형 레이아웃을 그대로 만들지 않고, 이미 93개
테이블·147개 통과 테스트로 검증된 기존 평면 레이아웃(`app/api/v1/routers/<domain>.py`,
`app/models/<domain>.py`, `app/schemas/<domain>.py`, `app/services/<domain>/`)에 도메인명
기준으로 매핑한다. `apps/worker/`는 아직 없으므로(BACKEND 트랙 net-new 예약 경로) 새로
만들되 내부 구조는 `src/jobs/<job>/` 대신 `app/jobs/<job>.py` 평면 구조를 따른다.

**근거**: DECISION-003/ASSUMPTION-002 연장 — 이미 검증된 기존 구조를 재구성하는 것보다
확장하는 편이 회귀 위험이 낮다. 또한 `apps/api/app/models/meeting.py`,
`app/models/integration.py`, `ai/`(query_interpreter.py 등)가 이미 존재하며 WAVE2C의
BACKEND-MEETING/AI-BUYER-MATCH 트랙과 상당 부분 겹친다 — 새 파일을 병렬로 만들지 않고
기존 파일을 확장하도록 각 에이전트에 명시 지시했다.

**되돌릴 수 있는가**: 예 — 파일 위치만의 문제이므로 추후 일괄 이동 가능.

**확인 필요 시점**: 사용자가 모듈형 레이아웃을 명시적으로 요구할 때.

## ASSUMPTION-004 (2026-08-02) — 검색 임베딩 v1의 운영 기본값

CR-004의 검색 임베딩은 `text-embedding-3-small` 512차원과 cosine을 권장 기본값으로 사용한다.
외부 임베딩 호출은 기본 비활성이며 운영자가 별도 키와 활성 플래그를 제공한 경우에만 실행한다.
새 모델이나 다른 차원은 기존 벡터를 제자리에서 덮어쓰지 않고 새 모델 버전·백필·검증·활성
포인터 교체 순서로 전환한다. 이 가정은 공급자 비용·개인정보 처리 검토 결과에 따라 새 CR로
교체할 수 있다.

---

## ASSUMPTION-005 (2026-08-11) — corrects a mis-citation: `apps/worker`'s zero-dependency rule was never covered by ASSUMPTION-003

**Correction, not a new independent choice**: the WAVE2C/2D/2E worktree's `apps/worker/pyproject.toml`
declared `dependencies = []` with an inline comment citing "ASSUMPTION-003" as its justification, and
`.harness/state.json` repeated the same citation ("zero third-party deps by design ... ASSUMPTION-003").
That citation is wrong: ASSUMPTION-003 (above) is scoped entirely to *file-layout* mapping
(`apps/api/src/modules/**` → the existing flat `app/**` layout) and says nothing about a dependency
policy. No prior assumption or decision anywhere in this file actually approved a zero-dependency rule
for `apps/worker` — it was asserted, not decided, and then cited to a document that never said it.

**Correction applied during the WAVE2C/2D/2E → main unification merge**: the zero-dependency premise
was also empirically false regardless of citation — `openpyxl>=3.1.5` is already an `apps/api`
dependency and main ships a 511-line production `openpyxl` reader
(`apps/api/app/services/excel_import.py`), so "the venv has no XLSX/PDF/DOCX libraries" was never
true once `apps/worker` runs alongside `apps/api`. Holding the rule anyway had already produced two
empirically unfit stdlib-only parsers in the worktree: its `XlsxParser` returns `SUCCEEDED` while
silently dropping every `inlineStr` cell, and its `PdfTextParser` returns zero segments for
hex-encoded CID Korean text while decoding literal-string Korean to mojibake and still reporting
`SUCCEEDED`. The merge therefore drops the zero-dependency rule for `apps/worker` and lets it declare
real dependencies (openpyxl, pypdf/pdf parsing, python-docx as needed), rewritten against
`apps/api/app/services/excel_import.py`'s hardened reader as the reference implementation rather than
against the stdlib.

**Also folded into this same correction**: `apps/worker`'s import root is renamed from `app` to
`worker`. In the worktree the collision with `apps/api`'s `app` import root was survivable because
the worker imported nothing from `apps/api`; in the unified repo it is fatal, because every real
worker job writes to `apps/api`'s own models and both packages now sit on `sys.path` simultaneously.
See `.harness/decisions.md` for the dated decision record of this rename.

**Reversible**: yes — this is a dependency-list and import-root correction, not a schema or API
change.

