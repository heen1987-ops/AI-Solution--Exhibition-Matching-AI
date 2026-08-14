/**
 * 모바일 반응형 스모크 테스트.
 *
 * docs/user-ia-wireframes.md 13.1절(모바일 폭 360~430px 기준)·13.2절(터치영역 44x44px
 * 이상)을 jsdom에서 완전히 검증할 수는 없지만(레이아웃 엔진이 없음), 이 테스트는 최소한
 * "좁은 뷰포트에서도 상담 화면의 핵심 조각들이 예외 없이 렌더링되고, 탭 가능한 액션들이
 * 이 앱의 44px 터치 영역 유틸리티(`tap-target`, `globals.css` 참고)를 쓰는지"를 확인한다.
 */

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import AlternateTimePicker from "../components/AlternateTimePicker";
import CancelDialog from "../components/CancelDialog";
import MeetingListItem from "../components/MeetingListItem";
import StatusBadge from "../components/StatusBadge";
import type { MeetingResponse, SlotCandidate } from "../types";

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

const slots: SlotCandidate[] = [
  { slot_id: "s1", start_at: "2026-08-05T02:00:00Z", end_at: "2026-08-05T02:30:00Z", preference_order: 1, request_status: "SELECTED" },
];

describe("mobile-responsive smoke test (360px viewport)", () => {
  const originalWidth = window.innerWidth;

  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: 360 });
    window.dispatchEvent(new Event("resize"));
  });

  afterEach(() => {
    Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: originalWidth });
  });

  it("renders the meeting list item without crashing and keeps its action tappable", () => {
    render(
      <ul>
        <MeetingListItem meeting={meeting({ status: "requested" })} />
      </ul>,
    );
    const action = screen.getByRole("link", { name: "요청 취소" });
    expect(action.className).toContain("tap-target");
  });

  it("renders the alternate-time picker's actions as tap targets", () => {
    render(<AlternateTimePicker candidateSlots={slots} isActing={false} onAccept={() => {}} onDeclineAll={() => {}} />);
    expect(screen.getByRole("button", { name: "이 시간 수락" }).className).toContain("tap-target");
    expect(screen.getByRole("button", { name: "모두 거절" }).className).toContain("tap-target");
  });

  it("renders the cancel dialog trigger as a tap target", () => {
    render(<CancelDialog isActing={false} confirmLabel="요청 취소" onConfirmCancel={() => {}} />);
    expect(screen.getByRole("button", { name: "요청 취소" }).className).toContain("tap-target");
  });

  it("renders the status badge without layout-only assumptions (no fixed pixel widths)", () => {
    render(<StatusBadge status="accepted" />);
    const badge = screen.getByText("확정");
    expect(badge.getAttribute("style") ?? "").not.toMatch(/width:\s*\d/);
  });
});
