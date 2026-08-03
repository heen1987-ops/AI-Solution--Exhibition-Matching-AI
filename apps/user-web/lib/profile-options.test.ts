import { describe, expect, it } from "vitest";

import {
  BUYER_CHANNEL_OPTIONS,
  BUYER_GOAL_OPTIONS,
  canonicalizeLegacyProfileCode,
  PRODUCT_CATEGORY_OPTIONS,
  SUPPLY_REGION_OPTIONS,
  profileCodeLabel,
  TASTE_OPTIONS,
  VISITOR_GOAL_OPTIONS,
} from "./profile-options";

describe("canonical profile options", () => {
  it("uses published ontology namespaces instead of legacy temporary codes", () => {
    expect(VISITOR_GOAL_OPTIONS.every((item) => item.code.startsWith("GOAL."))).toBe(true);
    expect(BUYER_GOAL_OPTIONS.every((item) => item.code.startsWith("BIZ_GOAL."))).toBe(true);
    expect(PRODUCT_CATEGORY_OPTIONS.every((item) => item.code.includes("."))).toBe(true);
    expect(TASTE_OPTIONS.every((item) => item.code.startsWith("TASTE.") || item.code.startsWith("AROMA."))).toBe(true);
    expect(BUYER_CHANNEL_OPTIONS.every((item) => item.code.startsWith("CHANNEL."))).toBe(true);
    expect(SUPPLY_REGION_OPTIONS.every((item) => item.code.startsWith("REGION.KR."))).toBe(true);
  });

  it("shows a safe readable fallback for newly published codes", () => {
    expect(profileCodeLabel("GOAL.TASTING")).toBe("시음");
    expect(profileCodeLabel("FUTURE.NEW_SIGNAL")).toBe("new signal");
  });

  it("migrates legacy in-browser goal values before the next save", () => {
    expect(canonicalizeLegacyProfileCode("TASTING")).toBe("GOAL.TASTING");
    expect(canonicalizeLegacyProfileCode("MARKET_RESEARCH")).toBe("BIZ_GOAL.MARKET_RESEARCH");
    expect(canonicalizeLegacyProfileCode("GOAL.TASTING")).toBe("GOAL.TASTING");
  });
});
