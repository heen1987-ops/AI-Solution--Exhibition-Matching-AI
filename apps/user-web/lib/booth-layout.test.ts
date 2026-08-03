import { describe, expect, it } from "vitest";

import { BOOTH_LAYOUT_STATUS, PROVISIONAL_BOOTH_ZONES } from "./booth-layout";

describe("provisional booth layout", () => {
  it("keeps every public-facing zone explicitly provisional", () => {
    expect(BOOTH_LAYOUT_STATUS).toBe("DRAFT_REFERENCE");
    expect(PROVISIONAL_BOOTH_ZONES).toHaveLength(6);
    expect(PROVISIONAL_BOOTH_ZONES.every((zone) => zone.status === "PROVISIONAL")).toBe(true);
  });

  it("does not invent finalized booth numbers or exhibitor placements", () => {
    expect(PROVISIONAL_BOOTH_ZONES.every((zone) => /^[A-F]$/.test(zone.id))).toBe(true);
    expect(PROVISIONAL_BOOTH_ZONES.some((zone) => /\d/.test(zone.id))).toBe(false);
  });
});
