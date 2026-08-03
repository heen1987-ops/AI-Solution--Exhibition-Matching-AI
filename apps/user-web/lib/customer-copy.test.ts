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
