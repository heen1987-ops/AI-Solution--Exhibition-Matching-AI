import { describe, expect, it } from "vitest";

import {
  REJECT_REASON_CODES,
  shouldRevealContact,
  validateDecisionInput,
} from "../logic";

describe("shouldRevealContact", () => {
  it("hides the contact before the meeting is accepted, even if a contact object is present", () => {
    expect(shouldRevealContact({ status: "requested", contact: { NAME: "홍길동" } })).toBe(false);
    expect(
      shouldRevealContact({ status: "counter_proposed", contact: { NAME: "홍길동" } }),
    ).toBe(false);
    expect(shouldRevealContact({ status: "rejected", contact: { NAME: "홍길동" } })).toBe(false);
  });

  it("hides the contact once accepted if the server did not actually disclose it", () => {
    expect(shouldRevealContact({ status: "accepted", contact: null })).toBe(false);
  });

  it("reveals the contact only when accepted AND the server returned contact fields", () => {
    expect(shouldRevealContact({ status: "accepted", contact: { NAME: "홍길동" } })).toBe(true);
  });
});

describe("validateDecisionInput", () => {
  it("requires a reason code on reject", () => {
    const errors = validateDecisionInput({ action: "REJECT", slotId: null, reasonCode: null });
    expect(errors.some((e) => e.field === "reasonCode")).toBe(true);
  });

  it("does not require a reason code on accept", () => {
    const errors = validateDecisionInput({
      action: "ACCEPT",
      slotId: "11111111-1111-4111-8111-111111111111",
      reasonCode: null,
    });
    expect(errors.some((e) => e.field === "reasonCode")).toBe(false);
  });

  it("requires a slot for accept and counter-propose", () => {
    expect(
      validateDecisionInput({ action: "ACCEPT", slotId: null, reasonCode: null }).some(
        (e) => e.field === "slotId",
      ),
    ).toBe(true);
    expect(
      validateDecisionInput({ action: "COUNTER_PROPOSE", slotId: null, reasonCode: null }).some(
        (e) => e.field === "slotId",
      ),
    ).toBe(true);
  });

  it("does not require a slot for reject", () => {
    expect(
      validateDecisionInput({ action: "REJECT", slotId: null, reasonCode: "OTHER" }),
    ).toEqual([]);
  });

  it("passes with no errors for a fully-filled accept", () => {
    expect(
      validateDecisionInput({
        action: "ACCEPT",
        slotId: "11111111-1111-4111-8111-111111111111",
        reasonCode: null,
      }),
    ).toEqual([]);
  });

  it("exposes at least one reject reason code option for the UI", () => {
    expect(REJECT_REASON_CODES.length).toBeGreaterThan(0);
  });
});
