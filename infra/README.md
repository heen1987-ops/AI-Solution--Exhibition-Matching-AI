# infra/

FOUNDATION 트랙 소유. 로컬·CI 실행 환경 관련 비-애플리케이션 자산.

- `docker/` - 앱별 Dockerfile. `backend.Dockerfile`(FastAPI, 빌드 컨텍스트는 저장소 루트) 존재. `apps/user-web·kiosk·admin·worker`는 아직 스캐폴딩 중이라 Dockerfile 없음 - 각 앱이 실제로 존재하게 되면 추가한다(`.github/workflows/ci.yml`의 `docker-build` 잡에 스텝 추가).
- `scripts/` - 운영 스크립트. `validate-harness`(하네스 자체 유효성 검사, FND 작업), `scope-violation-check`(범위 감시 스크립트) 위치.
- `monitoring/` - 아직 비어 있음. TESTING.md/SECURITY.md가 요구하는 관측 대상(API 응답시간·오류율, 워커 큐 적체, AI 호출 성공률)의 실제 설정 파일은 모니터링 스택 선택 이후 추가.
