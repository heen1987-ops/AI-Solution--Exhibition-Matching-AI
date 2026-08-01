# 백주대간 초개인화 AI 매칭서비스

기존 `backju.kr`와 CSV·API·웹훅으로 연결되는 독립형 전시회 매칭 플랫폼이다. 현재 1~15단계 설계와 후보검색·필터·점수·양면 적합도·상황 재정렬·다양성/공정성 노출제어 실행 기반을 포함한다.

## 현재 구현

- FastAPI 서비스 골격과 `/healthz`
- 온톨로지 조회·동의어 해석·수치 구간 API `/api/v1/ontology/*`
- 259개 v1 개념 정본, 관계·동의어·이벤트 매핑 검증기와 SQL 시드 생성 CLI
- PostgreSQL 온톨로지 스키마·불변성 트리거·Alembic 연결
- Netlify AI Gateway 기반 자연어 속성 구조화 내부 함수
- PostgreSQL/pgvector·Redis 로컬 인프라

## 빠른 검증

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
meet-ai-ontology validate
```

FastAPI 실행과 DB 적용 방법은 [`backend/README.md`](./backend/README.md), 전체 진행상태는 [`docs/00-roadmap.md`](./docs/00-roadmap.md)를 참조한다.
