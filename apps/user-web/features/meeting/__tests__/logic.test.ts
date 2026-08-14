import { describe, expect, it } from "vitest";

import {
  buildMeetingMessage,
  groupMeetingsByStatus,
  nextActionFor,
  shouldShowContactCard,
  toggleSlotSelection,
} from "../logic";
import type { MeetingResponse } from "../types";

function meeting(overrides: Partial<MeetingResponse>): MeetingResponse {
  return {
    meeting_id: "m1",
    status: "requested",
    exhibitor_id: "ex1",
    participation_id: "p1",
    topic_code: "DISTRIBUTION",
    message_preview: null,
    candidate_slots: [],
    confirmed_start: null,
    confirmed_end: null,
    contact_share_accepted: false,
    contact_share_fields: [],
    viewed_at: null,
    row_version: 0,
    created_at: "2026-08-02T00:00:00Z",
    updated_at: "2026-08-02T00:00:00Z",
    ...overrides,
  };
}

describe("toggleSlotSelection", () => {
  it("adds new slots up to the max (default 3)", () => {
    let selected: string[] = [];
    selected = toggleSlotSelection(selected, "a");
    selected = toggleSlotSelection(selected, "b");
    selected = toggleSlotSelection(selected, "c");
    expect(selected).toEqual(["a", "b", "c"]);
  });

  it("refuses to add a 4th slot once the max is reached", () => {
    const selected = toggleSlotSelection(["a", "b", "c"], "d");
    expect(selected).toEqual(["a", "b", "c"]);
  });

  it("always allows deselecting an already-selected slot even at the cap", () => {
    const selected = toggleSlotSelection(["a", "b", "c"], "b");
    expect(selected).toEqual(["a", "c"]);
  });

  it("respects a custom max", () => {
    expect(toggleSlotSelection(["a"], "b", 1)).toEqual(["a"]);
  });
});

describe("groupMeetingsByStatus", () => {
  it("groups meetings under their status and drops empty groups", () => {
    const meetings = [
      meeting({ meeting_id: "1", status: "requested" }),
      meeting({ meeting_id: "2", status: "accepted" }),
      meeting({ meeting_id: "3", status: "requested" }),
    ];
    const groups = groupMeetingsByStatus(meetings);
    const requestedGroup = groups.find((g) => g.status === "requested");
    const acceptedGroup = groups.find((g) => g.status === "accepted");
    expect(requestedGroup?.items.map((m) => m.meeting_id)).toEqual(["1", "3"]);
    expect(acceptedGroup?.items.map((m) => m.meeting_id)).toEqual(["2"]);
    expect(groups.find((g) => g.status === "rejected")).toBeUndefined();
  });

  it("returns no groups for an empty list", () => {
    expect(groupMeetingsByStatus([])).toEqual([]);
  });
});

describe("buildMeetingMessage", () => {
  it("returns null when every field is empty", () => {
    expect(buildMeetingMessage({})).toBeNull();
    expect(buildMeetingMessage({ productOrService: "  ", orderScale: "", freeText: null })).toBeNull();
  });

  it("labels product/order-scale fields and appends the free-text message", () => {
    const result = buildMeetingMessage({
      productOrService: "생막걸리 500ml",
      orderScale: "월 500박스",
      freeText: "가격표를 미리 받아볼 수 있을까요?",
    });
    expect(result).toBe(
      "제품/서비스: 생막걸리 500ml\n예상 발주 규모: 월 500박스\n\n가격표를 미리 받아볼 수 있을까요?",
    );
  });

  it("omits fields that are not provided", () => {
    expect(buildMeetingMessage({ freeText: "안녕하세요" })).toBe("안녕하세요");
  });
});

describe("shouldShowContactCard", () => {
  it("is false before acceptance even if contact is (incorrectly) present", () => {
    expect(
      shouldShowContactCard({ status: "requested", contact: { NAME: "홍길동" } }),
    ).toBe(false);
  });

  it("is false when accepted but the backend has not returned any contact fields yet", () => {
    expect(shouldShowContactCard({ status: "accepted", contact: null })).toBe(false);
    expect(shouldShowContactCard({ status: "accepted", contact: undefined })).toBe(false);
    expect(shouldShowContactCard({ status: "accepted", contact: {} })).toBe(false);
  });

  it("is true once accepted and at least one non-empty contact value exists", () => {
    expect(
      shouldShowContactCard({ status: "accepted", contact: { NAME: "홍길동", PHONE: "" } }),
    ).toBe(true);
  });
});

describe("nextActionFor", () => {
  it("returns a re-request action for cancelled meetings", () => {
    const action = nextActionFor({ status: "cancelled", meeting_id: "m1", exhibitor_id: "ex1" });
    expect(action).toEqual({ label: "다시 요청", href: "/meetings/new?exhibitorId=ex1" });
  });

  it("returns null for no_show", () => {
    expect(nextActionFor({ status: "no_show", meeting_id: "m1", exhibitor_id: "ex1" })).toBeNull();
  });
});
