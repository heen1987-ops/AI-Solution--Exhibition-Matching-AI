# AI 매칭 서비스 — 기술 설계 (DB 스키마 / API 명세 / 매칭 알고리즘)

> 상위 문서: [ai-matching-architecture.md](./ai-matching-architecture.md) 의 세부 구현 설계.
> 전제: 지금 단계에서는 backju.kr 관리자 계정/DB 직접 접근이 없으므로, **표준 스키마로 데이터를 "받아서" 적재하는 구조**로 설계한다 (Webhook/배치 export 수신). 실 연동 시 필드 매핑만 조정하면 되도록 최대한 사이트 종속성을 낮춘다.
>
> **보안 보정:** 최신 통합 기준은 [2026 대한민국 백주대간 초개인화 AI 매칭서비스 통합 설계안](./2026-backju-ai-matching-service-design.md)을 따른다. 특히 공개 위젯에 `visitorRef`를 직접 전달하지 않고 단기 서명 토큰을 사용하며, 웹훅 서명·멱등성·재시도, `tenant_id` 격리, 목적별 동의, 식별정보 분리를 구현해야 한다. 아래 DDL/API는 개념 초안이며 그대로 운영 배포하지 않는다.
> 외부 API와 내부 AI 계약의 최신 기준은 [프론트엔드·백엔드·AI 인터페이스 명세](./frontend-backend-ai-interface-spec.md)다.
> 데이터 모델의 최신 기준은 [DB ERD 상세설계 및 테이블 정의서](./db-erd-table-spec.md)다.

## 1. DB 스키마 (PostgreSQL + pgvector)

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 이벤트(전시회) 단위로 모든 데이터를 격리 (멀티테넌시 대비)
CREATE TABLE event (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_site  TEXT NOT NULL,               -- 'backju.kr'
  name         TEXT NOT NULL,
  starts_at    DATE,
  ends_at      DATE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 관심분야/제품태그/관람목적 공통 택소노미 (visitor.interests, exhibitor.product_tags가 이 code를 참조)
CREATE TABLE tag_taxonomy (
  code      TEXT PRIMARY KEY,               -- 'liquor.takju', 'purpose.business' 등
  label_ko  TEXT NOT NULL,
  category  TEXT NOT NULL CHECK (category IN ('interest','purpose','industry'))
);

CREATE TABLE visitor (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id            UUID NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  external_ref        TEXT,                 -- 원본 사이트 등록 ID (중복 수신 방지용)
  name                TEXT NOT NULL,
  gender              TEXT CHECK (gender IN ('M','F','UNKNOWN')) DEFAULT 'UNKNOWN',
  phone_hash          TEXT,                 -- HMAC-SHA-256(server secret, normalized phone), 원문 미보관
  email_hash          TEXT,
  region              TEXT,
  age_group           TEXT,
  interests           TEXT[] NOT NULL DEFAULT '{}',
  visit_purpose       TEXT[] NOT NULL DEFAULT '{}',
  referral_channel     TEXT,
  marketing_consent   BOOLEAN NOT NULL DEFAULT false,
  age_verified        BOOLEAN NOT NULL DEFAULT false,
  registered_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  consent_expires_at   TIMESTAMPTZ,          -- registered_at + 5년 (배치로 계산 삽입)
  profile_embedding    VECTOR(1536),         -- interests+purpose 텍스트 임베딩 (V1)
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (event_id, external_ref)
);
CREATE INDEX idx_visitor_event ON visitor(event_id);
CREATE INDEX idx_visitor_interests ON visitor USING GIN (interests);

CREATE TABLE exhibitor (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id                 UUID NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  company_name             TEXT NOT NULL,
  booth_no                 TEXT,
  industry_category         TEXT,
  product_tags             TEXT[] NOT NULL DEFAULT '{}',
  description               TEXT,
  target_visitor_purpose    TEXT[] NOT NULL DEFAULT '{}',
  contact_person            TEXT,
  contact_phone             TEXT,
  contact_email             TEXT,
  available_slots           JSONB NOT NULL DEFAULT '[]',   -- [{"start":"2026-09-01T10:00","end":"...","capacity":1}]
  status                    TEXT CHECK (status IN ('draft','approved','cancelled')) DEFAULT 'draft',
  description_embedding     VECTOR(1536),
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_exhibitor_event ON exhibitor(event_id);
CREATE INDEX idx_exhibitor_tags ON exhibitor USING GIN (product_tags);
CREATE INDEX idx_exhibitor_embedding ON exhibitor USING ivfflat (description_embedding vector_cosine_ops);

CREATE TABLE consult_session (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id            UUID NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  visitor_id          UUID REFERENCES visitor(id) ON DELETE SET NULL,
  started_at           TIMESTAMPTZ NOT NULL,
  ended_at             TIMESTAMPTZ,
  messages             JSONB NOT NULL DEFAULT '[]',   -- [{"role":"user|assistant","text":"...","ts":"..."}]
  extracted_intents    JSONB NOT NULL DEFAULT '{}',   -- {"interests":[...], "budget":"...", "mentioned_companies":[...]}
  summary               TEXT,
  summary_embedding     VECTOR(1536),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_consult_visitor ON consult_session(visitor_id);

CREATE TABLE match_result (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id       UUID NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  visitor_id     UUID NOT NULL REFERENCES visitor(id) ON DELETE CASCADE,
  exhibitor_id   UUID NOT NULL REFERENCES exhibitor(id) ON DELETE CASCADE,
  score          NUMERIC(5,4) NOT NULL,
  rank           INT NOT NULL,
  reason         TEXT,                                -- LLM이 생성한 개인화 추천 사유
  delivered_via  TEXT[] NOT NULL DEFAULT '{}',         -- {'widget','email','sms','kakao','chatbot'}
  delivered_at   TIMESTAMPTZ,
  feedback       TEXT CHECK (feedback IN ('none','clicked','visited','ignored')) DEFAULT 'none',
  feedback_at    TIMESTAMPTZ,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (visitor_id, exhibitor_id)
);
CREATE INDEX idx_match_visitor_rank ON match_result(visitor_id, rank);
```

설계 메모:
- `phone_hash`/`email_hash`만 저장하고 원문은 저장하지 않는 것을 기본값으로 한다 (§6 개인정보 정책과 정합). 알림톡/SMS 발송을 Meet AI Match가 직접 해야 한다면 별도 `contact_vault` 테이블을 암호화 저장소로 분리하고 접근을 제한한다 — 이 부분은 §9 미해결 질문(발송 주체)이 정해지면 확정.
- `event_id` 기준으로 모든 테이블이 격리되어 있어 향후 다른 전시회(멀티테넌시) 추가 시 스키마 변경이 필요 없다.
- `profile_embedding` / `description_embedding` / `summary_embedding` 은 MVP 단계에서는 NULL로 두고, V1에서 배치 잡으로 채운다.

## 2. API 명세

Base path: `/v1`. 인증은 이벤트 단위 API Key (`X-Api-Key` 헤더, 연동 사이트마다 발급).

### 2.1 데이터 수신 (Ingestion)

**`POST /v1/events/{eventId}/visitors`** — 사전등록 폼 제출 시 웹훅으로 호출 (또는 배치 upsert)

```json
// Request
{
  "external_ref": "reg_20260901_0001",
  "name": "홍길동",
  "gender": "M",
  "phone": "010-1234-5678",
  "email": "hong@example.com",
  "region": "서울·경기·인천",
  "age_group": "30대",
  "interests": ["liquor.takju", "liquor.spirits"],
  "visit_purpose": ["purpose.tasting", "purpose.business"],
  "referral_channel": "instagram",
  "marketing_consent": true,
  "age_verified": true
}
// Response 201
{ "id": "uuid", "status": "created" }
```
서버는 phone/email을 즉시 해시하여 저장하고 원문은 응답/로그에 남기지 않는다. `external_ref` 중복 시 upsert.

**`POST /v1/events/{eventId}/exhibitors`** — 참가기업 데이터 upsert (엑셀 일괄 업로드 배치 or 개별 등록)

```json
{
  "company_name": "OO양조장",
  "booth_no": "A-12",
  "industry_category": "전통주 제조",
  "product_tags": ["liquor.takju", "liquor.yakju"],
  "description": "3대째 이어온 전통 약주 양조장...",
  "target_visitor_purpose": ["purpose.purchase", "purpose.tasting"],
  "contact_person": "김담당",
  "contact_phone": "010-0000-0000",
  "contact_email": "contact@ooz.co.kr",
  "available_slots": [{"start": "2026-09-01T10:00", "end": "2026-09-01T18:00", "capacity": 20}],
  "status": "approved"
}
```

**`POST /v1/events/{eventId}/consult-sessions`** — AI상담 챗봇 세션 종료 시 배치 전송(또는 세션 중 스트리밍)

```json
{
  "visitor_external_ref": "reg_20260901_0001",
  "started_at": "2026-09-01T11:00:00+09:00",
  "ended_at": "2026-09-01T11:07:00+09:00",
  "messages": [
    {"role": "user", "text": "증류주 위주로 시음해보고 싶어요", "ts": "2026-09-01T11:01:00+09:00"},
    {"role": "assistant", "text": "증류주 전문 부스를 안내해드릴게요", "ts": "2026-09-01T11:01:05+09:00"}
  ]
}
```
서버가 `messages`를 받아 `extracted_intents`/`summary`/`summary_embedding`을 비동기로 생성한다 (클라이언트가 직접 계산해서 보낼 필요 없음).

### 2.2 매칭 조회

**`GET /v1/events/{eventId}/visitors/{visitorId}/matches?limit=5`**

```json
{
  "visitor_id": "uuid",
  "matches": [
    {
      "exhibitor_id": "uuid",
      "company_name": "OO양조장",
      "booth_no": "A-12",
      "score": 0.87,
      "rank": 1,
      "reason": "시음·이벤트 참여를 원하시고 증류주에 관심 있다고 하셔서 OO양조장 부스를 추천드려요."
    }
  ],
  "generated_at": "2026-09-01T09:00:00+09:00"
}
```
매칭이 아직 계산되지 않은 신규 방문객이면 202와 함께 `"status": "pending"` 반환 (비동기 파이프라인 실행 트리거).

**`POST /v1/events/{eventId}/matches/{matchId}/feedback`**

```json
{ "feedback": "visited" }  // 'clicked' | 'visited' | 'ignored'
```

### 2.3 임베드 위젯

**`GET /v1/embed/widget.js`** — 등록완료 페이지에 삽입하는 정적 위젯 로더. 원천 사이트 서버가 발급한 짧은 만료시간의 1회용 서명 토큰을 `data-match-token`으로 전달하고, 위젯은 토큰을 `Authorization` 헤더에 담아 매칭 API를 호출한다. 원본 `visitorRef`나 연락처를 브라우저 URL에 노출하지 않는다.

```html
<script
  src="https://match.example.com/v1/embed/widget.js"
  data-match-token="short-lived-signed-token"
  async
></script>
```

### 2.4 아웃바운드 Webhook (Meet AI → 사이트)

매칭이 새로 계산되면 사이트가 등록한 콜백 URL로 push (사이트가 이메일/알림톡 발송을 대행하는 경우):

```json
POST {site_callback_url}
{
  "event": "matches.computed",
  "visitor_external_ref": "reg_20260901_0001",
  "matches": [ { "exhibitor_id": "uuid", "company_name": "...", "reason": "..." } ]
}
```

## 3. 매칭 알고리즘

### 3.1 하드 필터 (스코어링 이전에 무조건 적용)

- `visitor.age_verified = true`
- `exhibitor.status = 'approved'`
- `visitor.event_id = exhibitor.event_id`

### 3.2 스코어 산식 (규칙 + 임베딩 혼합)

```
interest_overlap   = |visitor.interests ∩ exhibitor.product_tags| / |visitor.interests ∪ exhibitor.product_tags|   (Jaccard)
purpose_match       = 1 if (visitor.visit_purpose ∩ exhibitor.target_visitor_purpose) ≠ ∅ else 0
embedding_sim       = cosine(visitor.profile_embedding, exhibitor.description_embedding)     -- NULL이면 0
consult_sim         = max(cosine(session.summary_embedding, exhibitor.description_embedding) for 해당 visitor의 세션들)  -- 세션 없으면 0

가중치 (세션 유무에 따라 정규화):
  세션 있음: score = 0.30*interest_overlap + 0.15*purpose_match + 0.30*embedding_sim + 0.25*consult_sim
  세션 없음: score = 0.40*interest_overlap + 0.20*purpose_match + 0.40*embedding_sim
```
가중치는 초기값이며, `match_result.feedback` 누적 데이터로 추후 튜닝(§로드맵 V2 "자동튜닝"). 관리자 대시보드에서 이벤트별로 가중치 override 가능하도록 `event` 테이블에 `weight_config JSONB` 컬럼 확장 여지를 둔다.

### 3.3 파이프라인 단계

1. **후보 생성**: 하드 필터 통과한 exhibitor 중 `embedding_sim` 기준 pgvector `ivfflat` 인덱스로 top-30 검색.
2. **점수화**: top-30에 대해 §3.2 산식으로 score 계산, 정렬.
3. **LLM 재랭킹 (top-30 → top-5)**: 아래 프롬프트로 최종 순위·추천 사유 생성.
4. **저장**: `match_result`에 rank 1~5 upsert, 이전 결과와 비교해 변경분만 재전달.

### 3.4 LLM 재랭킹 프롬프트 템플릿

```
시스템: 당신은 전시회 방문객에게 부스를 추천하는 어시스턴트입니다.
아래 방문객 정보와 후보 부스 목록을 보고, 방문객에게 가장 도움이 될 상위 5개를 골라
순위와 1~2문장의 개인화된 추천 이유를 한국어로 작성하세요. 반드시 JSON으로만 응답하세요.

[방문객]
관심분야: {interests}
관람목적: {visit_purpose}
AI상담 요약: {consult_summary}  (없으면 "없음")

[후보 부스 (규칙 점수 순 top-30)]
1. {company_name} (부스 {booth_no}) - 태그: {product_tags} - 소개: {description}
...

출력 형식:
{"matches": [{"exhibitor_index": 1, "reason": "..."}]}
```
LLM 출력은 후보 인덱스 참조만 받고(할루시네이션 방지), 서버에서 실제 exhibitor_id로 매핑한다.

## 4. 오픈 이슈 (구현 착수 전 확정 필요)

- `contact_phone`/`email` 원문 보관 여부 — 알림톡/SMS 발송 주체가 Meet AI Match냐 사이트냐에 따라 스키마에 `contact_vault` 추가 여부 결정.
- 임베딩 모델 선정 (차원 수 1536은 예시, 실제 모델 확정 시 `VECTOR(n)` 조정 필요).
- `tag_taxonomy` 초기 데이터 — 백주대간 폼의 관심분야/관람목적 6종+4종을 기준으로 시드하되, 향후 다른 전시회 추가 시 카테고리 확장 방식 필요.
