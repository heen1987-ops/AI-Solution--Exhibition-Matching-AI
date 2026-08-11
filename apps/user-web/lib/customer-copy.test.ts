// @vitest-environment node
//
// 통합 시 추가: vitest.config.ts의 전역 environment는 features/**의 RTL 테스트를 위해
// "jsdom"이다. 이 파일은 실제 Node file:// URL 시맨틱(new URL(..., import.meta.url) +
// fileURLToPath)으로 소스 파일을 직접 읽는데, jsdom 환경에서는 그 URL이 file: 스킴이 아닌
// 것으로 취급돼 "The URL must be of scheme file"로 깨진다 - 이 파일만 다시 node 환경으로
// 되돌린다(포팅 전 main의 기본 동작과 동일 - 그때는 vitest.config.ts 자체가 없어 전역이
// node였다).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const CUSTOMER_VIEW_FILES = [
  new URL("../components/MyEventDashboard.tsx", import.meta.url),
  new URL("../components/PersonalizationProof.tsx", import.meta.url),
  new URL("../components/LocalRecommendationCard.tsx", import.meta.url),
];

const INTERNAL_COPY = [
  "기존 엑셀",
  "서비스 기획 맥락",
  "로컬 화면 검수용",
  "추천 Snapshot",
  "운영 매칭 엔진",
  "KAKAO DELIVERY CHECK",
  "발송 안 함",
];

describe("customer-facing copy", () => {
  it("does not expose internal review or delivery instructions", () => {
    const source = CUSTOMER_VIEW_FILES.map((url) => readFileSync(fileURLToPath(url), "utf8")).join("\n");

    for (const phrase of INTERNAL_COPY) {
      expect(source).not.toContain(phrase);
    }
  });
});
