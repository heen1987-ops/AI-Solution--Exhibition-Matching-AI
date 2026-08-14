import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ComparisonTable from "../ComparisonTable";
import { MAX_COMPARISON_ITEMS, type ComparisonExhibitor } from "../types";

const unknownExhibitor: ComparisonExhibitor = {
  exhibitor_id: "e1",
  company_name: "확인필요 양조장",
  company_summary: null,
  products: [],
  channels: null,
  moq: null,
  regions: null,
  oemAvailable: null,
  privateLabelAvailable: null,
  exportAvailable: null,
  meetingAvailableToday: null,
};

const knownFalseExhibitor: ComparisonExhibitor = {
  exhibitor_id: "e2",
  company_name: "확정정보 양조장",
  company_summary: "정보가 확실히 채워진 업체",
  products: [{ product_name: "청주", category_code: "ALCOHOL.CHEONGJU" }],
  channels: ["CHANNEL.HORECA"],
  moq: { min: 100, max: 500 },
  regions: ["REGION.KR.SEOUL"],
  oemAvailable: false,
  privateLabelAvailable: false,
  exportAvailable: true,
  meetingAvailableToday: false,
};

describe("ComparisonTable UNKNOWN rendering", () => {
  it("모든 필드가 UNKNOWN인 업체는 각 셀을 '확인 필요'로 보여주고, 빈 칸이나 '불가'로 보여주지 않는다", () => {
    render(<ComparisonTable exhibitors={[unknownExhibitor]} />);

    const table = screen.getByRole("region", { name: "업체 비교표" });
    // "제품·기술", "유통채널", "MOQ", "지역", "OEM", "PB", "수출", "상담" 8개 행 모두
    // '확인 필요' 셀이어야 한다.
    const unknownCells = within(table).getAllByTestId("comparison-unknown-cell");
    expect(unknownCells).toHaveLength(8);
    for (const cell of unknownCells) {
      expect(cell.textContent).toBe("확인 필요");
    }
    // UNKNOWN 필드에 대해 "불가"라는 글자가 표에 나타나면 안 된다(거짓 부정 금지).
    expect(within(table).queryByText("불가")).not.toBeInTheDocument();
  });

  it("실제로 조회에 성공해 false로 확인된 값은 '불가'로, UNKNOWN과 구분해 보여준다", () => {
    render(<ComparisonTable exhibitors={[knownFalseExhibitor]} />);
    const table = screen.getByRole("region", { name: "업체 비교표" });
    // OEM/PB/오늘 상담 3개는 실제로 false로 확인된 값이라 '불가'로 보여야 한다.
    expect(within(table).getAllByText("불가")).toHaveLength(3);
    // 확실히 아는 값이므로 '확인 필요' 셀이 없어야 한다.
    expect(within(table).queryAllByTestId("comparison-unknown-cell")).toHaveLength(0);
  });

  it("최대 비교 개수 상수는 4다", () => {
    expect(MAX_COMPARISON_ITEMS).toBe(4);
  });

  it("좁은 화면에서 표가 페이지 자체를 넘치게 하지 않도록 가로 스크롤 컨테이너 안에 있다(반응형 스모크 테스트)", () => {
    render(<ComparisonTable exhibitors={[knownFalseExhibitor]} />);
    const table = screen.getByRole("region", { name: "업체 비교표" });
    expect(table.className).toContain("overflow-x-auto");
  });
});
