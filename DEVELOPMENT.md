# DEVELOPMENT.md

## 로컬 인프라 기동

```bash
docker compose up -d
```

PostgreSQL(pgvector 포함, 포트 5432)과 Redis(포트 6379)가 기동된다. 헬스체크는 `docker-compose.yml` 참고.

## 백엔드 (FastAPI)

```bash
cd backend
python -m pip install -e ".[dev]"   # backend/pyproject.toml 참고, extras 이름은 실제 정의 확인
alembic upgrade head
uvicorn app.main:app --reload
```

`/healthz`로 기동 확인. API 문서는 FastAPI 기본 `/docs`(개발 환경 한정).

## 온톨로지·스코어링 코어 (`src/meet_ai`)

```bash
python -m pip install -e .          # 루트 pyproject.toml, meet-ai 패키지
meet-ai-ontology validate
python -m unittest discover -s tests -v
```

## 프런트엔드 (신규 - Wave 1부터)

`apps/user-web`, `apps/kiosk`, `apps/admin`은 Next.js/React/TypeScript/Tailwind로 신설한다(`FND-002` 이후). 각 앱의 실행 방법은 생성 시 이 문서에 추가한다.

## 작업 시작 전 확인 순서 (에이전트 공통)

1. `AGENTS.md` - 불변 규칙
2. `.harness/locks.yaml` - 내가 수정해도 되는 경로인지
3. `.harness/backlog.yaml` - 내가 맡은 태스크의 완료조건(`acceptance`)
4. `.harness/contracts/**` - 계약이 이미 고정됐는지(G1 이후는 CONTRACTS 트랙만 수정)

## 작업 루프 (메타프롬프트 §13)

UNDERSTAND → INSPECT → PLAN → IMPLEMENT → VERIFY → REVIEW → HANDOFF → CHECKPOINT. 각 단계를 생략하지 않는다 - 특히 VERIFY(자동 검증 실행)와 CHECKPOINT(상태파일 갱신)를 빠뜨리면 작업을 완료로 간주하지 않는다.

## 커밋·푸시

구현 단위가 관련 검증을 통과하면 의도적으로 커밋하고, 사용자가 달리 말하지 않는 한 `exhibition` git remote로 푸시한다(기존 관행, `AGENTS.md` §12).
