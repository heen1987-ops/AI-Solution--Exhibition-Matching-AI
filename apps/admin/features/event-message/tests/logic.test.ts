import { describe, expect, it } from "vitest";

import {
  InvalidTransitionError,
  SMALL_AUDIENCE_THRESHOLD,
  TARGET_SEGMENTS,
  TargetSegmentNotAllowedError,
  canTransition,
  findContentIssues,
  formatTargetCount,
  isEditable,
  isInternalDestinationScreen,
  requireTransition,
  statusAfterEdit,
  validateTargetSegment,
} from "../logic";
import type { MessageStatus } from "../types";

// ---------------------------------------------------------------------------
// 상태머신
// ---------------------------------------------------------------------------

describe("workflow transitions", () => {
  const allowed: [MessageStatus, MessageStatus][] = [
    ["DRAFT", "PREVIEWED"],
    ["PREVIEWED", "APPROVED"],
    ["PREVIEWED", "DRAFT"],
    ["APPROVED", "SCHEDULED"],
    ["APPROVED", "PUBLISHED"],
    ["APPROVED", "CANCELLED"],
    ["SCHEDULED", "PUBLISHED"],
    ["SCHEDULED", "CANCELLED"],
    ["PUBLISHED", "COMPLETED"],
  ];

  it.each(allowed)("allows %s -> %s", (from, to) => {
    expect(canTransition(from, to)).toBe(true);
    expect(() => requireTransition(from, to)).not.toThrow();
  });

  const disallowed: [MessageStatus, MessageStatus][] = [
    ["DRAFT", "APPROVED"],
    ["DRAFT", "PUBLISHED"],
    ["PREVIEWED", "PUBLISHED"],
    ["SCHEDULED", "DRAFT"],
    ["PUBLISHED", "CANCELLED"],
    ["COMPLETED", "PUBLISHED"],
    ["CANCELLED", "DRAFT"],
  ];

  it.each(disallowed)("rejects %s -> %s", (from, to) => {
    expect(canTransition(from, to)).toBe(false);
    expect(() => requireTransition(from, to)).toThrow(InvalidTransitionError);
  });

  it("resets PREVIEWED/APPROVED to DRAFT on edit", () => {
    expect(statusAfterEdit("PREVIEWED")).toBe("DRAFT");
    expect(statusAfterEdit("APPROVED")).toBe("DRAFT");
  });

  it("keeps DRAFT as DRAFT on edit", () => {
    expect(statusAfterEdit("DRAFT")).toBe("DRAFT");
  });

  it("returns null (not editable) for terminal/scheduled statuses", () => {
    for (const status of ["SCHEDULED", "PUBLISHED", "COMPLETED", "CANCELLED"] as MessageStatus[]) {
      expect(isEditable(status)).toBe(false);
      expect(statusAfterEdit(status)).toBeNull();
    }
  });
});

// ---------------------------------------------------------------------------
// 타겟 세그먼트 허용목록
// ---------------------------------------------------------------------------

describe("validateTargetSegment", () => {
  it("accepts every declared coarse segment", () => {
    for (const segment of TARGET_SEGMENTS) {
      const role = segment === "SPECIFIC_ROLE" ? "OPERATOR" : null;
      expect(() => validateTargetSegment(segment, role)).not.toThrow();
    }
  });

  it.each([
    "PROFILE_ATTRIBUTE:AGE_RANGE",
    "BEHAVIOR:VIEWED_BOOTH_3_TIMES",
    "INTEREST_CONCEPT:WHISKEY",
    "ALL_USERS",
    "",
  ])("rejects the disallowed fine-grained/sensitive segment %s", (segment) => {
    expect(() => validateTargetSegment(segment, null)).toThrow(TargetSegmentNotAllowedError);
  });

  it("rejects SPECIFIC_ROLE without a role code", () => {
    expect(() => validateTargetSegment("SPECIFIC_ROLE", null)).toThrow(
      TargetSegmentNotAllowedError,
    );
  });

  it("rejects a role code on a non-SPECIFIC_ROLE segment", () => {
    expect(() => validateTargetSegment("BUYERS", "BUYER")).toThrow(TargetSegmentNotAllowedError);
  });
});

// ---------------------------------------------------------------------------
// 소규모 대상 표시
// ---------------------------------------------------------------------------

describe("formatTargetCount", () => {
  it("uses the server-provided suppressed display string when target_count is null", () => {
    expect(formatTargetCount(null, `${SMALL_AUDIENCE_THRESHOLD}명 미만`)).toBe("5명 미만");
  });

  it("formats a real count with thousands separators", () => {
    expect(formatTargetCount(3214, "무시됨")).toBe("3,214명");
  });
});

// ---------------------------------------------------------------------------
// 내부 목적지 화면 판정
// ---------------------------------------------------------------------------

describe("isInternalDestinationScreen", () => {
  it.each(["/notifications", "/events/current"])("accepts %s", (path) => {
    expect(isInternalDestinationScreen(path)).toBe(true);
  });

  it.each(["https://example.com", "notifications", "//evil.example.com"])(
    "rejects %s",
    (path) => {
      expect(isInternalDestinationScreen(path)).toBe(false);
    },
  );
});

// ---------------------------------------------------------------------------
// 콘텐츠 정책 - script/tracking 거부
// ---------------------------------------------------------------------------

describe("findContentIssues", () => {
  it("finds no issues in safe markdown/HTML", () => {
    expect(findContentIssues("일반 텍스트 및 <b>강조</b>, <a href='/events/current'>링크</a>")).toEqual(
      [],
    );
  });

  it("flags <script> tags", () => {
    const issues = findContentIssues("<script>alert(1)</script>");
    expect(issues.some((i) => i.reasonCode === "TAG_NOT_ALLOWED")).toBe(true);
  });

  it("flags <img> tags (no tracking-pixel path)", () => {
    const issues = findContentIssues("<img src='https://tracker.example.com/pixel.gif'>");
    expect(issues.some((i) => i.reasonCode === "TAG_NOT_ALLOWED")).toBe(true);
  });

  it("flags event-handler attributes", () => {
    const issues = findContentIssues('<p onclick="alert(1)">클릭</p>');
    expect(issues.some((i) => i.reasonCode === "EVENT_HANDLER_ATTRIBUTE")).toBe(true);
  });

  it("flags javascript: links", () => {
    const issues = findContentIssues('<a href="javascript:alert(1)">링크</a>');
    expect(issues.some((i) => i.reasonCode === "DANGEROUS_URL_SCHEME")).toBe(true);
  });

  it("flags non-internal links for server-side allowlist review", () => {
    const issues = findContentIssues('<a href="https://evil.example.com">외부</a>');
    expect(issues.some((i) => i.reasonCode === "EXTERNAL_URL_NEEDS_SERVER_CHECK")).toBe(true);
  });
});
