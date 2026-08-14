import { describe, expect, it } from "vitest";

import {
  allowedActions,
  canManageBuyerVerification,
  canViewMeetingOps,
  isTransitionAllowed,
  redactPotentialContactInfo,
  targetStatusFor,
  validateReason,
} from "../logic";

describe("buyer verification state machine (작업 지시 필수 요구사항)", () => {
  it("allows PENDING -> VERIFIED / LIMITED / REJECTED only", () => {
    expect(allowedActions("PENDING").sort()).toEqual(["LIMIT", "REJECT", "VERIFY"]);
    expect(isTransitionAllowed("PENDING", "VERIFY")).toBe(true);
    expect(isTransitionAllowed("PENDING", "LIMIT")).toBe(true);
    expect(isTransitionAllowed("PENDING", "REJECT")).toBe(true);
    expect(isTransitionAllowed("PENDING", "SUSPEND")).toBe(false);
    expect(isTransitionAllowed("PENDING", "EXPIRE")).toBe(false);
  });

  it("allows VERIFIED -> SUSPENDED / EXPIRED only", () => {
    expect(allowedActions("VERIFIED").sort()).toEqual(["EXPIRE", "SUSPEND"]);
    expect(isTransitionAllowed("VERIFIED", "SUSPEND")).toBe(true);
    expect(isTransitionAllowed("VERIFIED", "EXPIRE")).toBe(true);
    expect(isTransitionAllowed("VERIFIED", "VERIFY")).toBe(false);
    expect(isTransitionAllowed("VERIFIED", "REJECT")).toBe(false);
  });

  it("allows no further transitions from terminal/administered states", () => {
    for (const status of ["LIMITED", "REJECTED", "SUSPENDED", "EXPIRED"]) {
      expect(allowedActions(status)).toEqual([]);
    }
  });

  it("computes the target status for an allowed transition", () => {
    expect(targetStatusFor("PENDING", "VERIFY")).toBe("VERIFIED");
    expect(targetStatusFor("PENDING", "LIMIT")).toBe("LIMITED");
    expect(targetStatusFor("PENDING", "REJECT")).toBe("REJECTED");
    expect(targetStatusFor("VERIFIED", "SUSPEND")).toBe("SUSPENDED");
    expect(targetStatusFor("VERIFIED", "EXPIRE")).toBe("EXPIRED");
  });

  it("returns null for a disallowed transition instead of guessing a target status", () => {
    expect(targetStatusFor("PENDING", "SUSPEND")).toBeNull();
    expect(targetStatusFor("REJECTED", "VERIFY")).toBeNull();
  });

  it("treats an unknown/open-enum status as having no allowed actions (fail closed)", () => {
    expect(allowedActions("SOME_FUTURE_STATUS")).toEqual([]);
    expect(isTransitionAllowed("SOME_FUTURE_STATUS", "VERIFY")).toBe(false);
  });
});

describe("validateReason (작업 지시 필수 요구사항: 모든 verify/limit/reject/suspend에 사유 필수)", () => {
  it("rejects an empty reason", () => {
    expect(validateReason("").ok).toBe(false);
    expect(validateReason("   ").ok).toBe(false);
  });

  it("rejects a reason shorter than the minimum length", () => {
    expect(validateReason("ab").ok).toBe(false);
  });

  it("accepts a sufficiently detailed reason", () => {
    expect(validateReason("사업자등록증 확인 완료").ok).toBe(true);
  });
});

describe("role gate (작업 지시 필수 요구사항: role-gated access)", () => {
  it("allows EVENT_ADMIN and DATA_REVIEWER to manage buyer verification", () => {
    expect(canManageBuyerVerification("EVENT_ADMIN")).toBe(true);
    expect(canManageBuyerVerification("DATA_REVIEWER")).toBe(true);
  });

  it("denies EXHIBITOR_ADMIN and unknown roles", () => {
    expect(canManageBuyerVerification("EXHIBITOR_ADMIN")).toBe(false);
    expect(canManageBuyerVerification("SOMETHING_ELSE")).toBe(false);
    expect(canManageBuyerVerification("")).toBe(false);
  });

  it("applies the same policy to the meeting ops view", () => {
    expect(canViewMeetingOps("EVENT_ADMIN")).toBe(true);
    expect(canViewMeetingOps("DATA_REVIEWER")).toBe(true);
    expect(canViewMeetingOps("EXHIBITOR_ADMIN")).toBe(false);
  });
});

describe("redactPotentialContactInfo (작업 지시 필수 요구사항: no raw contact-info leak)", () => {
  it("redacts an email address embedded in an otherwise safe display string", () => {
    expect(redactPotentialContactInfo("바이어 홍길동 (hong@example.com)")).toBe(
      "바이어 홍길동 ([REDACTED])",
    );
  });

  it("redacts a phone-number-like digit sequence", () => {
    expect(redactPotentialContactInfo("연락처 010-1234-5678")).toBe("연락처 [REDACTED]");
  });

  it("leaves an already-safe business identifier untouched", () => {
    expect(redactPotentialContactInfo("바이어 #a3f1 · 참가업체 술빚는집")).toBe(
      "바이어 #a3f1 · 참가업체 술빚는집",
    );
  });
});
