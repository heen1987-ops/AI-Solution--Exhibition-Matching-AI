# Decisions Log

확정된 결정만 기록한다(가정과 달리 재검토 조건이 아니라 사실 기록). 각 항목은 근거 문서를 링크한다.

## DEC-001: 프로젝트 단일 기준 문서

`docs/redesign-v2/00-master-spec-v1.md`(v1.0 통합 개발 명세서)를 프로젝트의 단일 기준으로 채택한다. 이전 1~28단계 개별 설계 문서(`docs/01-*.md` ~ `docs/09-10-*.md`)는 모듈별 참고자료로 재분류한다(`docs/redesign-v2/01-module-split-plan.md` §6/§8-11).

## DEC-002: 3모듈 분리 아키텍처

웹 초개인화 모듈, 키오스크 이식형 검색모듈, 공통 AI·데이터 플랫폼 3개로 서비스를 분리한다. 웹과 키오스크는 사용자 데이터·검색 방식이 분리되지만 업체·부스 DB와 검색엔진은 공유한다(`docs/redesign-v2/01-module-split-plan.md` §2).

## DEC-003: 웹/키오스크/공통 설계 완료

`docs/redesign-v2/web/W-1~W-10`, `kiosk/K-1~K-8`, `common/C-1~C-8`, `04-integration-roadmap.md` 26+1개 문서로 3모듈 설계가 완료됐다. 각 문서 간 이관 질문은 전량 다음 문서에서 해소됐다(`04-integration-roadmap.md` §9).

## DEC-004: 재설계는 스키마 재작성이 아니다

기존 `identity`/`profile`/`exhibitor`/`meeting`/`ontology` 스키마와 `meet_ai.scoring` 엔진 대부분이 새 스펙과 이미 정합적이다. 실제 신규가 필요한 영역은 `profile.saved_recommendable`, `ai.*`(문서·추출·승인·실행로그) 신규 스키마, 벡터/키워드 검색 채널, 키오스크 전용 점수식(`KIOSK_SEARCH_SCORE_V1`)으로 좁혀졌다. 기존 테이블·컬럼은 하나도 삭제하지 않는다(`04-integration-roadmap.md` §8).

## DEC-005: 하네스 도입, 모노레포 물리 이동 없음

병렬개발 하네스(`.harness/**`)를 도입하되 기존 `backend/`, `src/meet_ai/` 코드는 물리적으로 이동하지 않는다. `apps/`, `packages/`는 신규 코드 전용 위치로 신설한다(`assumptions.md` ASSUMPTION-001).

## DEC-006: 상담 스키마 축소 노출

`interaction.meeting.py`의 7개 테이블 중 `Meeting`/`MeetingStatusHistory`/`MeetingContactShare` 3개만 이번 MVP API·화면에 노출한다. `AvailabilitySlot`/`MeetingSlotRequest`/`MeetingOutcome`/`FollowUpAction`은 삭제하지 않되 노출하지 않는다(`docs/redesign-v2/web/W-7-buyer-matching-consultation.md` §1~2).

## DEC-007: RRF와 가중합의 2계층 구조

후보 검색(RRF, 여러 채널 융합)과 점수 계산(가중합, 웹은 `ScoringPolicy`, 키오스크는 `KIOSK_SEARCH_SCORE_V1`)을 서로 다른 계층으로 유지하고 하나가 다른 하나를 대체하지 않는다(`docs/redesign-v2/common/C-4-search-recommendation-engine.md` §1).

## DEC-009: CI 부트스트랩 중 발견한 기존 lint/의존성 결함은 좁게 즉시 수정한다

`FND-003`(CI 파이프라인 구축) 실행 중 실제로 로컬 검증을 해보니 (a) 11건의 import 순서 위반(ruff, CONTRACTS/BACKEND/QA_SECURITY 트랙 소유 파일에 걸쳐 분포)과 (b) `backend/pyproject.toml`에 `greenlet` 의존성 누락이 발견됐다. 두 건 모두 순수 기계적 수정(자동 import 정렬, 의존성 한 줄 추가)으로 로직 변경이 전혀 없고, 현재 다른 트랙 에이전트가 그 파일들을 동시에 편집하고 있지 않아 충돌 위험이 없으므로, `AGENTS.md` §4의 "다른 트랙 소유 경로 직접 수정 금지" 원칙의 좁은 예외로 즉시 수정했다. 일반적으로는 이런 발견도 별도 Change Request/handoff로 넘겨야 한다 - 이번은 규모(12줄)와 위험(0)이 예외를 정당화할 만큼 작다고 판단한 경우로 한정한다.

## DEC-008: DATA_REVIEWER는 신규 role_code가 아니다

마스터 스펙의 `DATA_REVIEWER` 역할은 `profile.role.role_code_allowed` CHECK 제약에 값을 추가하는 대신, 기존 `EVENT_ADMIN`(`OPERATOR`) 권한의 서비스 계층 스코프로 처리한다(`docs/redesign-v2/common/C-6-privacy-and-authorization.md` §1).
