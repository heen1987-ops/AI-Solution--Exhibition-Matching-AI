"""바이어 전용 매칭 오케스트레이션 (BACKEND-BUYER-MATCH, WAVE 2C).

하위 모듈
---------
- ``access``      : 바이어 자격(VERIFIED/LIMITED) 판정과 세션 소유권 검사.
- ``eligibility``  : 하드필터 판정(합격하지 못한 업체는 절대 결과에 나타나지 않는다).
- ``scoring``      : 하드필터를 통과한 후보의 점수·등급·근거코드·unknown_fields 계산.
- ``compare``      : ``POST /buyer/compare`` 전용 비교 뷰 구성(값 없음을 명시적으로 표시).
- ``orchestrator`` : 위 모듈을 조합해 matching.buyer_match_session을 생성·조회한다.
"""
