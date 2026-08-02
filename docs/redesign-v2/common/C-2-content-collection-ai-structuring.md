# C-2. 공통 AI·데이터 플랫폼 - 업체정보 수집·AI 구조화

근거 문서: `docs/redesign-v2/00-master-spec-v1.md`(§6 데이터 모델 - `source_document`/`extracted_attribute`/`content_approval`/`ai_execution_log`, §26~28), `docs/redesign-v2/01-module-split-plan.md`(§4-C C-2). [C-1 §4](C-1-exhibitor-booth-data-model.md)의 미결정 사항을 확정한다.

## 0. 핵심 결론: 여기서부터는 진짜 신규 구현이다

[C-1](C-1-exhibitor-booth-data-model.md)까지는 대부분 기존 자산 재발견이었지만, `source_document`/`extracted_attribute`/`content_approval`/`ai_execution_log`에 대응하는 테이블은 `backend/app/models/*.py` 전체에 **하나도 존재하지 않는다** - 이전 세션에서 이미 "vector/behavior/popularity 검색이 `ai.object_embedding` 등 인프라 부재로 막혀 있다"고 확인한 것과 같은 공백이다. C-2·C-4는 웹·키오스크 설계와 달리 재조정이 아니라 **순수 신규 스키마 설계**가 필요한 첫 영역이다.

## 1. 승인 흐름 - 기존 자산과의 접점

- `Exhibitor.master_approval_status`([C-1 §4](C-1-exhibitor-booth-data-model.md) 질문)는 `MASTER_APPROVAL_STATUSES = ("DRAFT", "APPROVED", "REJECTED")`로 확인했다 - 이는 "최종 승인 상태"만 담는 필드이고, **그 상태에 도달하기까지의 과정(참가신청서 제출 → AI 추출 → 업체 확인 → 운영자 승인)은 별도 추적 테이블이 없다.**
- **결정**: `master_approval_status`는 그대로 "최종 상태 요약 필드"로 유지하고, 그 상태 변경의 근거(어떤 소스 문서에서, 어떤 AI 추출 결과로 승인/반려됐는지)를 담는 이력 테이블을 신규로 추가한다(§2). 기존 컬럼을 없애거나 바꾸지 않는다.

## 2. 신규 테이블 설계 (마스터 스펙 §6 데이터 모델 재확인)

```text
ai.source_document        - 참가신청서·업체소개·제품자료 원본 (문서 유형, 업체/제품 FK, 저장 위치)
ai.extracted_attribute     - AI가 source_document에서 추출한 속성 후보
                              (attribute_code, value, confidence, 상태: PENDING/CONFIRMED/REJECTED)
ai.content_approval        - 운영자 승인 이력 (extracted_attribute 또는 문서 단위,
                              approved_by, approved_at, previous/new master_approval_status)
ai.ai_execution_log        - AI 호출 로그 (모델·프롬프트 버전, 입력 참조, 실행시간, 성공/실패)
```

- `ai.extracted_attribute`의 `attribute_code`는 `profile.ProfileAttribute`/`InferredPreference`([W-4](../web/W-4-profile-model.md))와 동일한 온톨로지 코드 체계를 공유한다 - 사용자 프로파일과 업체 속성이 같은 개념 사전(ontology)을 참조해야 매칭이 가능하기 때문이다. 이는 새 원칙이 아니라 기존 `ontology.concept`/`concept_revision` 설계가 이미 전제하고 있던 것.
- `ai.content_approval`이 승인을 확정하면 서비스 로직이 `Exhibitor.master_approval_status`를 갱신한다 - 즉 §1에서 "과정은 신규 테이블, 최종 상태는 기존 컬럼"이라는 역할 분담이 이 흐름으로 구현된다.

## 3. 참가신청서 → AI 추출 → 업체 확인 → 운영자 승인 흐름

```text
1. 참가업체가 참가신청서·소개자료·제품자료 업로드 → ai.source_document 생성
2. AI가 문서에서 속성 추출(관심분야 코드, 거래조건 등) → ai.extracted_attribute(PENDING)
   → 동시에 ai.ai_execution_log에 실행 기록
3. 참가업체가 추출 결과를 확인·수정(웹 관리자 화면, W-9 범위 밖 - admin 포털)
   → extracted_attribute.status가 CONFIRMED/REJECTED로 갱신
4. 운영자가 최종 승인 → ai.content_approval 생성, Exhibitor.master_approval_status = APPROVED
5. 승인된 속성만 실제 검색·추천에 노출(§4)
```

## 4. 미승인 데이터의 검색·추천 노출 차단

- **결정**: `master_approval_status != 'APPROVED'`인 업체는 [C-1 §2](C-1-exhibitor-booth-data-model.md)의 `Recommendable` 레지스트리에 등록하지 않는다(또는 등록하되 비활성 플래그) - 웹·키오스크 검색 결과에 미승인 업체가 노출되는 것을 원천 차단. 정확한 구현 방식(레지스트리 미등록 vs 비활성 플래그)은 C-4에서 검색 쿼리 설계와 함께 결정한다.

## 5. C-3으로 넘기는 질문

1. `ai.extracted_attribute`가 참조하는 온톨로지 코드가 사용자 프로파일과 완전히 동일한 체계인지, 아니면 업체 전용 하위 집합이 있는지 - C-3(관심분야 온톨로지)에서 확인.

## 6. C-4로 넘기는 질문

1. 미승인 업체의 정확한 검색 결과 차단 메커니즘(레지스트리 미등록 vs 비활성 플래그) - §4.
