"""AI 추천 방문 동선(U-13) 라우팅 엔진.

- ``pathfinding``  - DB/FastAPI에 의존하지 않는 순수 정렬·거리·시간 추정 함수.
- ``positioning``  - 현재 위치 추정 공급자 확장 포인트(``IndoorPositionSource``).
- ``service``      - 위 두 모듈과 DB를 엮어 실제 Route/RouteItem을 만들고 갱신하는 오케스트레이션.
"""

from __future__ import annotations
