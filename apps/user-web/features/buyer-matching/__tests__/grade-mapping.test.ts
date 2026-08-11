import { describe, expect, it } from "vitest";

import { buildInfoNeededFields, gradeFromMatchLevel } from "../types";
import type { ExhibitorPublicSummary } from "../types";

describe("gradeFromMatchLevel", () => {
  it("VERY_HIGH/HIGH는 HIGH 등급으로, MEDIUM은 MEDIUM으로, LOW는 POSSIBLE로 변환한다", () => {
    expect(gradeFromMatchLevel("VERY_HIGH")).toBe("HIGH");
    expect(gradeFromMatchLevel("HIGH")).toBe("HIGH");
    expect(gradeFromMatchLevel("MEDIUM")).toBe("MEDIUM");
    expect(gradeFromMatchLevel("LOW")).toBe("POSSIBLE");
  });
});

describe("buildInfoNeededFields", () => {
  it("업체 정보를 아예 못 받아오면 업체 정보 자체를 확인 필요로 표시한다", () => {
    expect(buildInfoNeededFields(null)).toEqual(["업체 정보"]);
  });

  it("일부 필드만 비어 있으면 그 필드만 확인 필요 목록에 담는다(값을 지어내지 않는다)", () => {
    const exhibitor: ExhibitorPublicSummary = {
      exhibitor_id: "e1",
      company_name: "테스트 양조장",
      company_summary: null,
      product_count: 2,
      booth_id: "b1",
      booth_number: "A-01",
    };
    expect(buildInfoNeededFields(exhibitor)).toEqual(["업체 소개"]);
  });

  it("모든 필드가 채워져 있으면 빈 배열을 반환한다(빈 배열 자체가 명시적인 값)", () => {
    const exhibitor: ExhibitorPublicSummary = {
      exhibitor_id: "e1",
      company_name: "테스트 양조장",
      company_summary: "전통 방식으로 빚는 막걸리 양조장입니다.",
      product_count: 3,
      booth_id: "b1",
      booth_number: "A-01",
    };
    expect(buildInfoNeededFields(exhibitor)).toEqual([]);
  });
});
