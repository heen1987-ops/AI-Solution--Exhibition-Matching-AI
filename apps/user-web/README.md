# 백주 AI 셀파 - 프론트엔드

2026 대한민국 백주대간 초개인화 AI 매칭서비스의 사용자·참가업체 웹 프론트엔드다.
Next.js 14 App Router + TypeScript + Tailwind CSS로 구성한 기반 골격이며, 이후 화면
에이전트들이 이 위에 실제 라우트(온보딩, 홈, 탐색, 지도, 일정, MY, 참가업체 포털)를
채워 넣는다.

## 요구 사항

- Node.js 18.18 이상
- 백엔드 API 서버(`apps/api/`)가 별도 오리진에서 떠 있어야 한다(같은 저장소, 다른 실행
  프로세스).
- 이 저장소는 pnpm workspace다 — 루트에서 `pnpm install` 한 번으로 모든 앱의 의존성이 설치된다.
  개별 실행은 `pnpm --filter backju-ai-sherpa-frontend dev` 또는 아래처럼 디렉터리에서 직접.

## 시작하기

```bash
cd apps/user-web
npm install   # 또는 루트에서 pnpm install
cp .env.example .env.local   # NEXT_PUBLIC_API_BASE_URL을 백엔드 주소로 맞춘다
npm run dev
```

`http://localhost:3000`에서 확인한다. 타입만 검사하려면 `npm run typecheck`, 린트는
`npm run lint`.

> **Google Drive 동기화 경로 주의**: 이 저장소가 Google Drive로 동기화되는 폴더
> 안에 있으면(`G:\내 드라이브\...` 등) `npm install`이 tar 압축 해제 도중 실시간
> 동기화와 충돌해 일부 패키지 파일(`node_modules/typescript/package.json` 등)이
> 빈 파일로 깨질 수 있다(설치 자체는 exit code 0으로 "성공"한 것처럼 보이므로
> 알아채기 어렵다). `npm run typecheck`/`npm run build`가 `ERR_INVALID_PACKAGE_CONFIG`
> 등으로 실패하면 Google Drive 동기화를 일시중지하거나, 동기화 대상이 아닌 로컬
> 경로(예: `C:\dev\...`)에 프로젝트를 두고 설치하는 것을 권장한다. 실제로 이 문제로
> 여기서도 설치가 두 번 깨졌다가 로컬 경로에서는 정상 설치·빌드됨을 확인했다.

## 환경 변수

| 변수 | 설명 |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | 백엔드 API 오리진(예: `http://localhost:8000`). 비우면 같은 오리진 상대경로(`/api/v1/...`)로 호출한다. |
| `NEXT_PUBLIC_EVENT_ID` | 검색·추천 대상 행사의 UUID. 배포 시 필수이며 미설정/형식 오류이면 게스트 검색은 fail-closed로 안내한다. |
| `NEXT_PUBLIC_NAVER_MAP_NCP_KEY_ID` | NAVER Cloud Maps Dynamic Map의 Web SDK용 Client ID/Key ID. Client Secret은 프론트엔드에 넣지 않는다. |

### 네이버 지도 활성화

1. NAVER Cloud Platform 콘솔의 VPC 환경에서 `Application Services > Maps` 이용을
   신청한 뒤 Application을 등록하고 `Dynamic Map`을 선택한다.
2. Web 서비스 URL에 로컬 검수 주소와 운영 대표 도메인을 등록한다. 현재 로컬 검수 주소는
   `http://127.0.0.1:3137`이다.
3. 인증 정보에서 확인한 Web SDK용 **Client ID/Key ID**만 `.env.local`의
   `NEXT_PUBLIC_NAVER_MAP_NCP_KEY_ID`에 넣고 웹을 다시 빌드한다. Client Secret/API
   Secret은 브라우저 환경변수나 소스에 넣지 않는다.

```dotenv
NEXT_PUBLIC_NAVER_MAP_NCP_KEY_ID=발급받은_WEB_SDK_CLIENT_ID
```

Web Dynamic Map 키는 등록한 Web 서비스 URL과 실제 접속 도메인이 다르면 인증에 실패한다.
운영 도메인이 정해지면 해당 대표 도메인도 Maps Application에 추가한다.

이 화면은 확대·축소, 마커, 사용자 요청 기반 현재 위치 표시가 필요한 동적 지도이므로
Static Map의 `/raster` 또는 `/raster-cors`로 대체하지 않는다. REST API 인증이 필요한
기능을 추가할 때는 Client Secret을 브라우저에 전달하지 않고 서버 어댑터에서 호출한다.

## 디렉터리 구조

```text
apps/user-web/
  app/
    layout.tsx       루트 레이아웃 - TopBar + 하단 탭(BottomNav) 전역 배치, 접근성 골격
    globals.css       Tailwind 기본 + 접근성 기준(16px 이상 본문, 44x44 터치영역 등)
  components/
    TopBar.tsx        상단 공통 영역(행사명, 방문일, 구역+위치갱신, 동기화 상태)
    BottomNav.tsx     하단 탭(홈/탐색/지도/일정/MY)
  lib/
    api-client.ts     백엔드 REST API 타입드 fetch 래퍼 (공용 - 아래 참고)
    types.ts          요청/응답 TypeScript 타입 (공용 - 아래 참고)
  .env.example
  package.json / tsconfig.json / next.config.js / tailwind.config.ts / postcss.config.js
```

## 공용 파일: `lib/api-client.ts`, `lib/types.ts`

이 두 파일은 여러 화면 에이전트가 동시에 가져다 쓰는 공용 파일이다. **다른 작업에서
이 두 파일을 직접 수정하지 말고 import만 한다.** 새 엔드포인트가 필요하면 이 파일들에
정식으로 추가하거나(선호), 급하면 `apiGet/apiPost/apiPut/apiPatch/apiDelete` 저수준
헬퍼를 임시로 쓴다.

`api-client.ts`가 다루는 네 가지 핵심 흐름과 대표 함수:

- **온보딩**: `createProfileSession`(세션 생성), `patchProfileSession`(사용자 유형),
  `postAnswers`(목적·취향·바이어조건·방문계획 - 온보딩 단계별 판별 유니언),
  `updateProfilePreferences`(추천 조건 수정), `getProfile` 등.
- **추천**: `getRecommendations`(세션 ID 유무에 따라 홈/전체 목록으로 분기),
  `createRecommendationSession`, `getRecommendationSessionItems`.
- **인터랙션**: `postInteraction`(단건), `postInteractions`(배치).
- **상담**: `postMeetingRequest`, `patchMeetingRequest`(취소/응답 판별 유니언),
  `getExhibitorAvailability`, 참가업체 포털용 `listPartnerMeetings` 등.

그 외 저장(`favorites`), 경로(`routes`), QR 체크인·피드백, 부스·제품 상세 조회도
포함되어 있으나, 해당 백엔드 라우터가 아직 구현되지 않은 경우가 있다(각 함수/타입
주석의 TODO 참고 - 인터페이스 명세 문서의 예시 JSON과 db-erd 컬럼 설명을 근거로 잠정
정의했다). 백엔드 스키마가 확정되면 `types.ts`의 해당 인터페이스만 대조해 맞추면 된다.

모든 함수는 실패 시 `ApiClientError`(코드/메시지/필드오류/재시도가능여부 포함)를
던진다. 화면에서는 `error.code`로 19절 오류 코드 표의 UI 처리를 분기한다.

이 클라이언트는 오프라인 큐잉·재전송을 구현하지 않는다(11.4절). QR 체크인·피드백·
상담요청처럼 오프라인 허용이 필요한 화면은 이 클라이언트 위에 로컬 큐를 얹어야 한다.

## 참고한 설계 문서

- `docs/user-ia-wireframes.md` - 1절(UX 원칙), 4절(글로벌 내비게이션), 5.1절(라우트
  표), 9절(컴포넌트 기준), 13절(반응형·접근성)
- `docs/frontend-backend-ai-interface-spec.md` - 2.4절(시간·문자열·금액 규칙), 4절(API
  공통 계약), 6~17절(도메인별 엔드포인트 계약)
