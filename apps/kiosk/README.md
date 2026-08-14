# 백주 AI 셀파 — 현장 키오스크

로그인이나 개인정보 입력 없이 행사장에서 승인된 업체·제품·부스를 찾고, 선택 결과를
서명된 만료 QR로 휴대폰에 보내는 독립 Next.js 앱이다.

## 실행

백엔드와 Redis/PostgreSQL을 먼저 실행한 뒤 저장소 루트에서:

```powershell
pnpm install
Copy-Item apps/kiosk/.env.example apps/kiosk/.env.local
pnpm dev:kiosk
```

기본 주소는 `http://localhost:3200`이다. 사용자 웹은 QR 도착점인
`http://localhost:3000/kiosk-handoff?token=...`을 제공하므로 함께 실행하려면
`pnpm dev:user-web`도 별도 터미널에서 실행한다.

환경변수:

- `NEXT_PUBLIC_API_BASE_URL`: FastAPI 오리진. 기본 로컬 값 `http://localhost:8000`.
- `NEXT_PUBLIC_KIOSK_ID`: 단말 식별 코드. 사람을 식별하는 값이 아니다.

## 구현 흐름

- K00 대기, K01 언어 선택(ko/en/ja/zh)
- K02~K05 자연어·추천문·카테고리 검색과 승인 업체 결과
- K06~K08 업체 상세, 부스 위치, 서명 QR 인계
- K09 결과 없음, K10 네트워크 오류, 세션 종료 자동 복귀

세션은 서버 설정에 따라 60~120초 무입력 시 초기화된다. 브라우저 상태는
`sessionStorage`에만 두며 검색어·결과·QR 토큰은 종료/만료/처음 화면 복귀 시 함께 삭제한다.
이름·전화번호·이메일·비밀번호 입력 UI와 로그인 기능은 의도적으로 없다.

## 검증

```powershell
pnpm --filter backju-kiosk test
pnpm --filter backju-kiosk typecheck
pnpm --filter backju-kiosk build
```

Google Drive 동기화 경로에서는 pnpm의 symlink/rename이 충돌할 수 있다. 그런 경우 동기화
대상이 아닌 로컬 디렉터리에서 설치·검증한다.
