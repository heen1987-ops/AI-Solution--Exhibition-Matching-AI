import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ContactInfoCard from "../components/ContactInfoCard";
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
    confirmed_start: "2026-08-05T01:00:00Z",
    confirmed_end: "2026-08-05T01:30:00Z",
    contact_share_accepted: false,
    contact_share_fields: [],
    viewed_at: null,
    row_version: 0,
    created_at: "2026-08-02T00:00:00Z",
    updated_at: "2026-08-02T00:00:00Z",
    ...overrides,
  };
}

describe("ContactInfoCard", () => {
  it("renders nothing before the meeting is accepted", () => {
    const { container } = render(
      <ContactInfoCard meeting={meeting({ status: "requested", contact: { NAME: "홍길동" } })} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when accepted but the backend has not returned contact fields yet (no broken placeholder)", () => {
    const { container } = render(<ContactInfoCard meeting={meeting({ status: "accepted", contact: null })} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when accepted but the contact object is empty", () => {
    const { container } = render(<ContactInfoCard meeting={meeting({ status: "accepted", contact: {} })} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders known contact fields plus the meeting time once accepted and populated", () => {
    render(
      <ContactInfoCard
        meeting={meeting({
          status: "accepted",
          contact: { NAME: "홍길동", BUSINESS_EMAIL: "hong@brewery.example" },
        })}
      />,
    );
    expect(screen.getByText("담당자 이름")).toBeInTheDocument();
    expect(screen.getByText("홍길동")).toBeInTheDocument();
    expect(screen.getByText("업무용 이메일")).toBeInTheDocument();
    expect(screen.getByText("hong@brewery.example")).toBeInTheDocument();
    expect(screen.getByText("상담 시간")).toBeInTheDocument();
  });
});
