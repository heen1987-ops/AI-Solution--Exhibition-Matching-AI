# packages/

`apps/*` 프런트엔드가 공유하는 TypeScript 패키지의 위치 (npm workspaces 멤버). 아직 비어 있다.

예정된 패키지(`.harness/locks.yaml` 소유권 기준):

- `shared-types/` - CONTRACTS 트랙 소유. `.harness/contracts/openapi.yaml`(CTR-002) 확정 후 자동/수동 생성.
- `api-client/` - CONTRACTS 트랙 소유.
- `validation/` - CONTRACTS 트랙 소유.
- `config/` - CONTRACTS 트랙 소유.
- `ui/` - 소유 트랙 미정(Wave 2 시작 시 결정, `.harness/locks.yaml` 하단 메모 참고).
- `search/` - AI_SEARCH 트랙 소유.

생성된 클라이언트 타입(`api-client` 등)은 수동 편집하지 않는다(`AGENTS.md` §7).
