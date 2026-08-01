# AI-Solution — Exhibition Matching AI

백주대간 초개인화 AI 매칭서비스: 전시회 관람객(일반 관람객·바이어)과 참가업체·제품을 매칭하는 추천 플랫폼.

## 문서

설계 스펙은 [`docs/design/`](docs/design/)에 있다.

- [DB ERD 상세설계 및 테이블 정의서](docs/design/06-db-erd-schema-design.md)
- [사용자 프로파일 모델 설계](docs/design/07-user-profile-model.md)
- [참가업체·제품 프로파일 모델 설계](docs/design/08-exhibitor-product-profile-model.md)
- [후보검색·검색 인덱스 설계](docs/design/09-candidate-search-design.md)

## 기술 스택 (MVP)

- **DB**: PostgreSQL + pgvector
- **캐시**: Redis
- **DB 마이그레이션**: [`db/migrations/`](db/migrations/)

## 구조

```
docs/design/     설계 스펙 (ERD, 프로파일 모델, 후보검색 등)
db/migrations/   PostgreSQL DDL 마이그레이션
```
