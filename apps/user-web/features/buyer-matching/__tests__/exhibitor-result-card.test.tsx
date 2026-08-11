import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ComparisonSelectionProvider } from "@/features/exhibitor-comparison/comparison-selection";

vi.mock("@/lib/api-client", () => ({
  ApiClientError: class ApiClientError extends Error {},
  createFavorite: vi.fn(),
  deleteFavorite: vi.fn(),
  postInteraction: vi.fn().mockResolvedValue(undefined),
}));

import ExhibitorResultCard from "../ExhibitorResultCard";
import type { MatchingCardData } from "../types";

function makeCard(overrides: Partial<MatchingCardData> = {}): MatchingCardData {
  return {
    item: {
      match_result_id: "m1",
      rank: 1,
      object_type: "EXHIBITOR",
      object_id: "e1",
      exhibitor_id: "e1",
      match_level: "HIGH",
      reasons: [{ code: "GOAL_MATCH", text: "관심 목적과 잘 맞아요", evidence_refs: [] }],
      availability: {},
      recommended_action: "REQUEST_MEETING",
    },
    grade: "HIGH",
    exhibitor: {
      exhibitor_id: "e1",
      company_name: "테스트 양조장",
      company_summary: null,
      product_count: 0,
      booth_id: "b1",
      booth_number: "A-01",
    },
    exhibitorLoadFailed: false,
    infoNeededFields: ["업체 소개", "취급 제품"],
    ...overrides,
  };
}

function renderCard(data: MatchingCardData, verificationStatus: "VERIFIED" | "UNVERIFIED" = "VERIFIED") {
  return render(
    <ComparisonSelectionProvider>
      <ExhibitorResultCard data={data} verificationStatus={verificationStatus} />
    </ComparisonSelectionProvider>,
  );
}

describe("ExhibitorResultCard", () => {
  it("등급을 숫자 점수가 아니라 정성적 라벨로 보여준다", () => {
    renderCard(makeCard());
    const badge = screen.getByTestId("match-grade-badge");
    expect(badge.textContent).not.toMatch(/\d/);
  });

  it("정보가 부족한 필드는 '확인 필요' 칩으로 명확히 표시하고, 빈 칸으로 감추지 않는다", () => {
    renderCard(makeCard());
    const chips = screen.getAllByTestId("info-needed-chip");
    expect(chips.map((chip) => chip.textContent)).toEqual(["업체 소개 확인 필요", "취급 제품 확인 필요"]);
  });

  it("정보가 다 채워져 있으면 '확인 필요' 칩을 아예 렌더링하지 않는다", () => {
    renderCard(makeCard({ infoNeededFields: [] }));
    expect(screen.queryByTestId("info-needed-chip")).not.toBeInTheDocument();
  });

  it("인증되지 않은 바이어에게는 상담 요청 CTA 대신 인증 필요 안내를 보여준다", () => {
    renderCard(makeCard(), "UNVERIFIED");
    expect(screen.queryByRole("link", { name: "상담 요청" })).not.toBeInTheDocument();
    expect(screen.getByText("상담 요청(인증 필요)")).toBeInTheDocument();
  });

  it("인증된 바이어에게는 상담 요청 CTA를 보여준다", () => {
    renderCard(makeCard(), "VERIFIED");
    expect(screen.getByRole("link", { name: "상담 요청" })).toHaveAttribute(
      "href",
      "/meetings/new?exhibitorId=e1",
    );
  });

  it("주요 조작 버튼은 모바일 최소 터치영역(44x44) 유틸리티 클래스를 갖는다(반응형 스모크 테스트)", () => {
    renderCard(makeCard());
    const compareButton = screen.getByRole("button", { name: /비교하기/ });
    const saveButton = screen.getByRole("button", { name: /저장/ });
    expect(compareButton.className).toContain("tap-target");
    expect(saveButton.className).toContain("tap-target");
  });
});
