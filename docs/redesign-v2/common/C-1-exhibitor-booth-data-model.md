# C-1. 공통 AI·데이터 플랫폼 - 업체·부스 데이터 모델

근거 문서: `docs/redesign-v2/00-master-spec-v1.md`(§6 데이터 모델 목록, §57), `docs/redesign-v2/01-module-split-plan.md`(§4-C C-1). 웹([W-1~W-10](../web/))·키오스크([K-1~K-8](../kiosk/)) 설계 전체가 전제로 삼은 "업체·부스 DB"의 실체를 확인한다.

## 0. 핵심 결론: 이미 마스터 스펙보다 상세한 스키마가 있다

마스터 스펙 §6은 `exhibitor`, `event_participation`, `booth`, `product_service`, `exhibitor_interest`, `public_trade_condition`, `booth_status` 정도의 플랫(flat) 테이블 목록을 제시하지만, `backend/app/models/exhibitor.py`에는 이미 20개 테이블(`Exhibitor`, `ExhibitorBusinessType`, `ExhibitorParticipation`, `ParticipationCategory`, `ExhibitorStaff`, `StaffTopic`, `Product`, `EventProduct`, `ProductAttribute`, `ProductImage`, `TradeCondition`, `TradeConditionTerm`, `Booth`, `BoothStatusHistory`, `BoothQr`, `Program`, `ExhibitorProfile`, `ProductProfile`, `SupplyCapability`, `ExhibitorBuyerPreference`, `SupplyProfileAttribute`)이 구현되어 있다. **재설계가 아니라 "마스터 스펙의 뭉뚱그려진 이름을 기존 세분화된 테이블 집합에 매핑"하는 작업이다.**

## 1. 매핑 표

| 마스터 스펙 §6 | 기존 테이블 | 비고 |
| --- | --- | --- |
| `exhibitor` | `Exhibitor` + `ExhibitorBusinessType` | `master_approval_status`(승인 상태), `data_completeness_percent`가 이미 있어 C-2(AI 구조화·승인)의 기반이 됨 |
| `event_participation` | `ExhibitorParticipation` + `ParticipationCategory` | 행사별 참가 단위 - 업체(`Exhibitor`)와 행사 참가(`ExhibitorParticipation`)가 분리돼 있어, 한 업체가 여러 행사에 재참가하는 구조를 이미 지원 |
| `booth` | `Booth` + `BoothStatusHistory` + `BoothQr` | [K-5](../kiosk/K-5-map-location-qr.md)의 QR 부스 안내와 `BoothQr`이 직접 대응 - **키오스크 QR(모바일 인계)과 부스 QR(부스 위치 안내)은 서로 다른 메커니즘**임을 명확히 구분해야 함(§3에서 상세) |
| `product_service` | `Product` + `EventProduct` + `ProductAttribute` + `ProductImage` | `Product`(업체의 제품 마스터)와 `EventProduct`(특정 행사에서의 노출 상태 - tasting/purchase_status 등, 이전 세션에서 이미 활용)가 분리 |
| `exhibitor_interest` | `ExhibitorProfile` + `ProductProfile` + `SupplyProfileAttribute` | 업체·제품의 온톨로지 개념 연결(관심분야 태깅) |
| `public_trade_condition` | `TradeCondition` + `TradeConditionTerm` | 이전 세션에서 이미 oem/pb/export 상태를 바이어 매칭 점수에 반영 |
| `booth_status`(운영상태) | `BoothStatusHistory` | congestion_level/estimated_wait_minutes 등 - 이전 세션에서 이미 context_reranker에 연결 |
| (스펙에 명시 안 됨) | `SupplyCapability`/`ExhibitorBuyerPreference` | 바이어 매칭(B2B) 점수의 capacity/buyer_type/channel/region 컴포넌트 근거 - 마스터 스펙 §6 목록에는 없지만 §57 Buyer Match Score 컴포넌트를 위해 반드시 필요한 테이블이므로, 신설이 아니라 **누락된 항목을 기존 자산에서 재발견**한 것으로 처리 |

## 2. `Recommendable` 레지스트리와의 관계

이전 세션(구 아키텍처)에서 구현한 `exhibition.recommendable`(추천 후보를 부스/제품 등 여러 객체 타입에 대해 다형성 없이 참조하는 레지스트리, "폴리모픽 FK 제거" 목적)은 마스터 스펙 §6에 대응 개념이 없다. **이 레지스트리는 그대로 유지한다** - [W-8 §4](../web/W-8-api-and-db-changes.md)의 `saved_recommendable`이 이 레지스트리에 의존하고, [K-4](../kiosk/K-4-natural-language-search-logic.md)의 검색 결과도 궁극적으로 이 레지스트리의 ID를 반환하기 때문이다. 마스터 스펙이 이 개념을 언급하지 않는 것은 "없어도 된다"는 뜻이 아니라 "구현 세부사항이라 상위 스펙 문서에 안 나온 것"으로 해석한다.

## 3. 부스 QR과 키오스크 QR의 구분 (K-5 보강)

- `BoothQr`(부스 자체에 부착된 QR - 스캔하면 그 부스 상세 페이지로 이동, 아마도 방문객이 각 부스를 돌며 스캔)과 [K-5 §3](../kiosk/K-5-map-location-qr.md)의 "키오스크 화면에 표시되는 QR"(스캔하면 검색 결과 목록을 모바일로 인계)은 **서로 다른 기능**이다 - 전자는 정적 QR(부스마다 고정), 후자는 동적 QR(세션마다 새로 발급). 화면 IA·API 설계 시 이름 혼동에 주의해야 한다는 점만 여기서 명시하고, `BoothQr`의 상세 사양은 C-1의 기존 자산이므로 이 문서에서 추가로 설계하지 않는다.

## 4. C-2로 넘기는 질문

1. `Exhibitor.master_approval_status`/`data_completeness_percent`가 C-2(업체정보 수집·AI 구조화)의 승인 흐름과 정확히 어떻게 연동되는지(자동 계산되는 필드인지, 운영자가 수동 갱신하는지) - C-2에서 확인.
