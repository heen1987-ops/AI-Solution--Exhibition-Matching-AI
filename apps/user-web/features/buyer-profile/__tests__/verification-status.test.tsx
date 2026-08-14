import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import VerificationStatusBanner, { canRequestMeeting } from "../VerificationStatusBanner";
import type { BuyerVerification, BuyerVerificationStatus } from "../types";

function verification(overrides: Partial<BuyerVerification> = {}): BuyerVerification {
  return {
    status: "UNVERIFIED",
    restriction_note: null,
    decision_reason: null,
    reviewed_at: null,
    is_authoritative: true,
    ...overrides,
  };
}

describe("VerificationStatusBanner", () => {
  it.each<BuyerVerificationStatus>(["UNVERIFIED", "PENDING"])(
    "%s 상태에서는 열람 제한과 상담 요청에 인증이 필요하다는 안내를 보여준다",
    (status) => {
      render(<VerificationStatusBanner verification={verification({ status })} />);
      const banner = screen.getByTestId("verification-status-banner");
      expect(banner).toHaveAttribute("data-status", status);
      expect(banner.textContent).toMatch(/인증/);
      expect(canRequestMeeting(status)).toBe(false);
    },
  );

  it("VERIFIED 상태에서는 모든 기능 이용 가능 안내를 보여주고 상담 요청을 허용한다", () => {
    render(<VerificationStatusBanner verification={verification({ status: "VERIFIED" })} />);
    expect(screen.getByTestId("verification-status-banner").textContent).toContain("모든 기능");
    expect(canRequestMeeting("VERIFIED")).toBe(true);
  });

  it("LIMITED 상태에서는 서버가 준 구체적 제한 사유를 그대로 보여준다", () => {
    render(
      <VerificationStatusBanner
        verification={verification({ status: "LIMITED", restriction_note: "월 주문 조회만 가능해요." })}
      />,
    );
    expect(screen.getByTestId("verification-status-banner").textContent).toContain("월 주문 조회만 가능해요.");
  });

  it("LIMITED 상태에서 서버가 사유를 안 주면 일반 안내 문구로 대체한다(빈 문구를 보여주지 않는다)", () => {
    render(<VerificationStatusBanner verification={verification({ status: "LIMITED" })} />);
    const banner = screen.getByTestId("verification-status-banner");
    expect(banner.querySelector("p")?.textContent?.trim().length).toBeGreaterThan(0);
  });

  it.each<BuyerVerificationStatus>(["REJECTED", "SUSPENDED"])(
    "%s 상태에서는 문의 경로만 제공하고 마치 다시 시도하면 될 것처럼 보이는 버튼을 넣지 않는다",
    (status) => {
      render(<VerificationStatusBanner verification={verification({ status, decision_reason: "서류 미비" })} />);
      const banner = screen.getByTestId("verification-status-banner");
      expect(banner.textContent).toContain("서류 미비");

      // 문의 링크(mailto)는 있어야 한다.
      const contactLink = screen.getByRole("link", { name: /문의하기/ });
      expect(contactLink).toHaveAttribute("href", expect.stringMatching(/^mailto:/));

      // "다시 시도"류의 버튼은 없어야 한다 - 실제로 상태를 못 바꾸는데 될 것처럼 보이면 안 됨.
      expect(screen.queryByRole("button", { name: /다시\s*시도|재시도|retry/i })).not.toBeInTheDocument();
      expect(canRequestMeeting(status)).toBe(false);
    },
  );
});
