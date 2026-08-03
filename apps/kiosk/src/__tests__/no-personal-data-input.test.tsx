import type React from "react";
import { describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";

import { WaitingScreen } from "@/components/screens/WaitingScreen";
import { LanguageScreen } from "@/components/screens/LanguageScreen";
import { SearchScreen } from "@/components/screens/SearchScreen";
import { ResultsScreen } from "@/components/screens/ResultsScreen";
import { ExhibitorDetailScreen } from "@/components/screens/ExhibitorDetailScreen";
import { MapScreen } from "@/components/screens/MapScreen";
import { QrScreen } from "@/components/screens/QrScreen";
import { ErrorScreen } from "@/components/screens/ErrorScreen";
import { HealthScreen } from "@/components/screens/HealthScreen";

/**
 * 하드 요구사항 검증 (AGENTS.md §8, PROJECT_SCOPE.md 키오스크 제외범위,
 * .harness/worker-prompts.md 핵심 제약): 키오스크의 어떤 화면에도 로그인,
 * 전화번호, 이메일, 그 밖의 개인정보 입력 컨트롤이 존재해서는 안 된다.
 *
 * 이 테스트는 이번 웨이브에서 스캐폴딩한 모든 화면(K-S1~K-S8, /health)의
 * 렌더링 결과에서 다음을 확인한다:
 *  1. `input[type="password" | "email" | "tel"]`가 단 하나도 없다.
 *  2. `autocomplete`가 이름/연락처/계정 계열 값으로 설정된 입력이 없다.
 *  3. name/id/placeholder/aria-label에 로그인·개인정보 연상 키워드
 *     (이메일/전화/휴대폰/비밀번호/로그인/성명/이름/주민등록/카드번호 등)가
 *     없다. (K-S3의 자연어 검색창처럼 "검색어" 계열 입력은 개인정보가 아니므로
 *     허용된다 - 아래 정규식은 그런 입력을 오탐하지 않도록 구체적인 개인정보
 *     키워드만 사용한다.)
 *  4. `<form>`이 있다면 개인정보 전송을 암시하는 method="post" + 이름/이메일류
 *     input 조합이 아니다(검색 폼은 허용).
 */

beforeEach(() => {
  // HealthScreen이 마운트 시 시도하는 백엔드 연결 확인(fetch)을 결정론적으로
  // 즉시 실패시켜, 테스트가 실제 네트워크에 의존하지 않고 act() 경고 없이
  // 안정적으로 끝나도록 한다(연결상태 자체의 정확성은 이 테스트의 관심사가 아님 -
  // 오직 "개인정보 입력 필드가 없다"만 검증한다).
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new Error("no backend in test env"))
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const PERSONAL_DATA_KEYWORD_PATTERN =
  /(email|e-mail|이메일|메일주소|phone|tel(ephone)?|mobile|전화번호|휴대(폰|전화)|연락처|password|비밀번호|passwd|login|로그인|아이디|username|user-name|account|계좌|카드번호|card-?number|ssn|주민(등록)?번호|생년월일|address|주소|성명|실명|본인인증)/i;

const DISALLOWED_INPUT_TYPES = new Set(["password", "email", "tel"]);
const DISALLOWED_AUTOCOMPLETE = new Set([
  "email",
  "tel",
  "name",
  "given-name",
  "family-name",
  "username",
  "current-password",
  "new-password",
  "cc-number",
  "cc-name",
  "street-address",
  "postal-code",
]);

function assertNoPersonalDataInputs(container: HTMLElement, screenName: string) {
  const fields = Array.from(
    container.querySelectorAll("input, textarea, select")
  );

  for (const field of fields) {
    const type = field.getAttribute("type");
    const name = field.getAttribute("name") ?? "";
    const id = field.getAttribute("id") ?? "";
    const placeholder = field.getAttribute("placeholder") ?? "";
    const ariaLabel = field.getAttribute("aria-label") ?? "";
    const autocomplete = field.getAttribute("autocomplete") ?? "";

    if (type && DISALLOWED_INPUT_TYPES.has(type)) {
      throw new Error(
        `[${screenName}] 금지된 input type="${type}"이(가) 발견되었습니다.`
      );
    }

    if (autocomplete && DISALLOWED_AUTOCOMPLETE.has(autocomplete.toLowerCase())) {
      throw new Error(
        `[${screenName}] 개인정보 계열 autocomplete="${autocomplete}"가 발견되었습니다.`
      );
    }

    for (const [attrName, value] of [
      ["name", name],
      ["id", id],
      ["placeholder", placeholder],
      ["aria-label", ariaLabel],
    ] as const) {
      if (value && PERSONAL_DATA_KEYWORD_PATTERN.test(value)) {
        throw new Error(
          `[${screenName}] 필드의 ${attrName}="${value}"가 개인정보 연상 키워드와 일치합니다.`
        );
      }
    }
  }

  // 로그인 폼을 암시하는 <form> 구성 요소 자체가 없는지도 확인한다.
  const forms = Array.from(container.querySelectorAll("form"));
  for (const form of forms) {
    const hasPasswordField = form.querySelector('input[type="password"]');
    if (hasPasswordField) {
      throw new Error(`[${screenName}] <form> 내부에 비밀번호 입력이 있습니다.`);
    }
  }
}

describe("키오스크 화면 - 개인정보 입력 컨트롤 부재 검증 (AGENTS.md §8)", () => {
  const screens: Array<[string, React.ReactElement]> = [
    ["K-S1 대기화면", <WaitingScreen key="waiting" />],
    ["K-S2 언어 선택", <LanguageScreen key="language" />],
    ["K-S3 검색 진입", <SearchScreen key="search" />],
    ["K-S4 결과 목록", <ResultsScreen key="results" />],
    ["K-S4 결과 목록(빈 상태)", <ResultsScreen key="results-empty" exhibitors={[]} />],
    [
      "K-S5 업체·부스 상세",
      <ExhibitorDetailScreen key="detail" exhibitorId="exh-001" />,
    ],
    ["K-S6 지도", <MapScreen key="map" />],
    ["K-S7 QR 화면", <QrScreen key="qr" />],
    ["K-S8 오류화면(generic)", <ErrorScreen key="error-generic" variant="generic" />],
    ["K-S8 오류화면(network)", <ErrorScreen key="error-network" variant="network" />],
    [
      "K-S8 오류화면(qr-handoff)",
      <ErrorScreen key="error-qr" variant="qr-handoff" />,
    ],
    ["/health 설정·연결상태", <HealthScreen key="health" />],
  ];

  it.each(screens)(
    "%s 화면에 개인정보 입력 필드가 없다",
    async (name, element) => {
      const { container } = render(element);
      // HealthScreen처럼 마운트 후 비동기로 상태를 갱신하는 화면이 있을 수
      // 있으므로, 단언 전에 보류 중인 마이크로태스크를 한 번 비워준다.
      await act(async () => {
        await Promise.resolve();
      });
      assertNoPersonalDataInputs(container, name);
    }
  );

  it("검증 헬퍼 자체가 실제로 위반을 탐지한다(회귀 방지용 반증 테스트)", () => {
    const { container } = render(
      <form>
        <input type="email" name="email" placeholder="이메일을 입력하세요" />
      </form>
    );
    expect(() => assertNoPersonalDataInputs(container, "가짜 로그인 폼")).toThrow();
  });
});
