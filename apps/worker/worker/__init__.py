"""BAC-001 apps/worker 골격 패키지.

RQ(Redis Queue)를 사용하는 최소 백그라운드 잡 워커 골격. 실제 AI 문서처리·임베딩
생성은 이 웨이브에서 구현하지 않는다(PROJECT_SCOPE.md 제외범위, BAC-001 acceptance) -
큐 연결, 샘플 작업, 재시도 정책, 구조화 로그만 제공하는 스캐폴딩이다.
"""

from __future__ import annotations
