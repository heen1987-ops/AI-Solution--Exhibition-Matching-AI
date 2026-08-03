import { describe, expect, it } from "vitest";

import { parseLocalPersonalizationPreview } from "./personalization-preview";

const validPreview = {
  displayName: "테스트 사용자",
  maskedPhone: "010-****-0000",
  registeredAt: "2026-08-03 16:53:02",
  sourceLabel: "온라인 사전등록",
  interests: ["우리술", "양조기술"],
  goals: ["비즈니스"],
  needsReview: true,
  notificationConsent: true,
  recommendations: [
    {
      exhibitorName: "테스트 양조장",
      productName: "탁주",
      categoryLabel: "우리술",
      boothLabel: "부스 미정",
      matchLabel: "잘 맞음",
      reasons: ["우리술 관심과 일치"],
      informationStatus: "부스 미정",
    },
  ],
};

describe("local personalization preview", () => {
  it("accepts bounded masked test data", () => {
    const parsed = parseLocalPersonalizationPreview(JSON.stringify(validPreview));
    expect(parsed?.displayName).toBe("테스트 사용자");
    expect(parsed?.recommendations).toHaveLength(1);
    expect(parsed?.recommendations[0]?.matchLabel).toBe("관심분야 관련 업체");
  });

  it("rejects a raw phone number or email-like contact", () => {
    expect(
      parseLocalPersonalizationPreview(
        JSON.stringify({ ...validPreview, maskedPhone: "010-1234-5678" }),
      ),
    ).toBeNull();
    expect(
      parseLocalPersonalizationPreview(
        JSON.stringify({ ...validPreview, maskedPhone: "person@example.com" }),
      ),
    ).toBeNull();
  });

  it("fails closed on malformed recommendation data", () => {
    expect(
      parseLocalPersonalizationPreview(
        JSON.stringify({ ...validPreview, recommendations: [{ exhibitorName: "불완전" }] }),
      ),
    ).toBeNull();
  });
});
