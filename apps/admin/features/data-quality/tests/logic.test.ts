import { describe, expect, it } from "vitest";

import {
  COMPLETENESS_FACTORS,
  computeCompletenessScore,
  dataQualityCheckStatusLabel,
  requiredFieldsPercentLabel,
  sortByCompletenessAscending,
  sortChecksByStatusSeverity,
  thresholdRatio,
  toCompletenessInput,
} from "../logic";
import type { CompletenessInput, DataQualityCheckSummary, ExhibitorDataQualityRow } from "../types";

function fullInput(overrides: Partial<CompletenessInput> = {}): CompletenessInput {
  return {
    required_fields_present: 10,
    required_fields_total: 10,
    product_count: 5,
    interest_code_count: 5,
    has_booth: true,
    has_public_intro: true,
    approval_status: "PUBLISHED",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// 핵심 불변조건: 완성도 점수는 오직 데이터 존재 요소만으로 계산한다 (스펙 명시)
// ---------------------------------------------------------------------------

describe("completeness score formula excludes popularity/CTR", () => {
  it("COMPLETENESS_FACTORS enumerates exactly the 6 data-presence factors, weights summing to 100", () => {
    expect(COMPLETENESS_FACTORS.map((f) => f.factor)).toEqual([
      "required_fields",
      "product_count",
      "interest_code_count",
      "has_booth",
      "has_public_intro",
      "approval_status",
    ]);
    expect(COMPLETENESS_FACTORS.reduce((sum, f) => sum + f.weight, 0)).toBe(100);
  });

  it("none of the factor names reference popularity, CTR, clicks, views, or favorites", () => {
    const banned = /click|ctr|popular|view|impression|favorite|즐겨찾기|클릭|조회|인기/i;
    for (const f of COMPLETENESS_FACTORS) {
      expect(f.factor).not.toMatch(banned);
      expect(f.label_ko).not.toMatch(banned);
    }
  });

  it("is unaffected by extraneous popularity/CTR-shaped fields smuggled onto the input object", () => {
    const clean = fullInput();
    const withPopularityFields = {
      ...clean,
      click_through_rate: 0.99,
      clicks: 999999,
      views: 999999,
      popularity_score: 100,
      favorites_count: 500,
    } as CompletenessInput & Record<string, unknown>;

    const cleanScore = computeCompletenessScore(clean);
    const pollutedScore = computeCompletenessScore(withPopularityFields);

    expect(pollutedScore).toEqual(cleanScore);
  });

  it("scores a fully-complete exhibitor at 100", () => {
    expect(computeCompletenessScore(fullInput()).score).toBe(100);
  });

  it("scores a completely-empty exhibitor at 0", () => {
    const empty = fullInput({
      required_fields_present: 0,
      required_fields_total: 10,
      product_count: 0,
      interest_code_count: 0,
      has_booth: false,
      has_public_intro: false,
      approval_status: "DRAFT",
    });
    expect(computeCompletenessScore(empty).score).toBe(0);
  });

  it("treats zero required-fields-total as trivially satisfied (nothing to miss)", () => {
    const score = computeCompletenessScore(
      fullInput({ required_fields_present: 0, required_fields_total: 0 }),
    );
    const requiredFactor = score.factors.find((f) => f.factor === "required_fields");
    expect(requiredFactor?.attainment).toBe(1);
  });

  it("only APPROVED or PUBLISHED count as full approval-status attainment", () => {
    const draft = computeCompletenessScore(fullInput({ approval_status: "DRAFT" }));
    const rejected = computeCompletenessScore(fullInput({ approval_status: "REJECTED" }));
    const approved = computeCompletenessScore(fullInput({ approval_status: "APPROVED" }));
    const published = computeCompletenessScore(fullInput({ approval_status: "PUBLISHED" }));

    expect(draft.score).toBeLessThan(published.score);
    expect(rejected.score).toBeLessThan(published.score);
    expect(approved.score).toBe(published.score);
  });

  it("gives partial credit for a half-complete required-fields set", () => {
    const half = computeCompletenessScore(
      fullInput({ required_fields_present: 5, required_fields_total: 10 }),
    );
    const factor = half.factors.find((f) => f.factor === "required_fields");
    expect(factor?.attainment).toBe(0.5);
    expect(factor?.points).toBe(15); // weight 30 * 0.5
  });

  it("caps product/interest-code attainment at 1 beyond the presence target (not an unbounded popularity-style count)", () => {
    const modest = computeCompletenessScore(fullInput({ product_count: 3, interest_code_count: 3 }));
    const huge = computeCompletenessScore(fullInput({ product_count: 500, interest_code_count: 500 }));
    expect(modest.score).toBe(huge.score);
  });
});

describe("toCompletenessInput (row -> input projection)", () => {
  it("only carries the 6 data-presence fields, dropping everything else on the row", () => {
    const row: ExhibitorDataQualityRow = {
      exhibitor_id: "ex-1",
      exhibitor_name: "화요양조",
      required_fields_present: 8,
      required_fields_total: 10,
      product_count: 2,
      interest_code_count: 1,
      unresolved_trade_condition_unknown_count: 3,
      document_review_status: "APPROVED",
      search_index_status: "INDEXED",
      has_booth: true,
      has_public_intro: false,
      approval_status: "APPROVED",
      last_modified_at: "2026-08-01T00:00:00Z",
    };
    const input = toCompletenessInput(row);
    expect(Object.keys(input).sort()).toEqual(
      [
        "required_fields_present",
        "required_fields_total",
        "product_count",
        "interest_code_count",
        "has_booth",
        "has_public_intro",
        "approval_status",
      ].sort(),
    );
  });
});

describe("sortByCompletenessAscending", () => {
  it("surfaces the least-complete exhibitor first and does not mutate the input array", () => {
    const rows: ExhibitorDataQualityRow[] = [
      {
        exhibitor_id: "complete",
        exhibitor_name: null,
        required_fields_present: 10,
        required_fields_total: 10,
        product_count: 5,
        interest_code_count: 5,
        unresolved_trade_condition_unknown_count: 0,
        document_review_status: "APPROVED",
        search_index_status: "INDEXED",
        has_booth: true,
        has_public_intro: true,
        approval_status: "PUBLISHED",
        last_modified_at: null,
      },
      {
        exhibitor_id: "incomplete",
        exhibitor_name: null,
        required_fields_present: 1,
        required_fields_total: 10,
        product_count: 0,
        interest_code_count: 0,
        unresolved_trade_condition_unknown_count: 4,
        document_review_status: "NONE",
        search_index_status: "NOT_INDEXED",
        has_booth: false,
        has_public_intro: false,
        approval_status: "DRAFT",
        last_modified_at: null,
      },
    ];
    const copy = [...rows];
    const sorted = sortByCompletenessAscending(rows);
    expect(sorted.map((r) => r.exhibitor_id)).toEqual(["incomplete", "complete"]);
    expect(rows).toEqual(copy);
  });
});

describe("requiredFieldsPercentLabel", () => {
  it("formats a present/total percentage", () => {
    expect(requiredFieldsPercentLabel(3, 4)).toBe("3/4 (75%)");
  });

  it("reports 해당 없음 when there are no required fields defined", () => {
    expect(requiredFieldsPercentLabel(0, 0)).toBe("해당 없음");
  });
});

// ---------------------------------------------------------------------------
// 파이프라인 헬스체크 롤업 - BACKEND-ANALYTICS의 실제 착지 스키마
// (analytics.data_quality_snapshot: 체크 코드별 OK/WARN/FAIL) 기준.
// 2026-08-03 재조정으로 옛 issueResolutionRate/sortIssuesBySeverityThenOpenCount
// (존재하지 않는 이슈 open/resolved 집계 가정)를 대체했다 - ../types.ts 참고.
// ---------------------------------------------------------------------------

describe("sortChecksByStatusSeverity / dataQualityCheckStatusLabel / thresholdRatio", () => {
  function check(overrides: Partial<DataQualityCheckSummary> = {}): DataQualityCheckSummary {
    return {
      check_code: "INGESTION_LATENCY_P95_SECONDS",
      status: "OK",
      metric_value: null,
      threshold_value: null,
      affected_count: null,
      ...overrides,
    };
  }

  it("sorts FAIL before WARN before OK", () => {
    const checks = [
      check({ check_code: "z-ok", status: "OK" }),
      check({ check_code: "a-fail", status: "FAIL" }),
      check({ check_code: "m-warn", status: "WARN" }),
    ];
    const sorted = sortChecksByStatusSeverity(checks);
    expect(sorted.map((c) => c.check_code)).toEqual(["a-fail", "m-warn", "z-ok"]);
  });

  it("breaks ties within the same status alphabetically by check_code", () => {
    const checks = [
      check({ check_code: "SUBJECT_UNKNOWN_RATE", status: "WARN" }),
      check({ check_code: "LATE_ARRIVAL_RATE", status: "WARN" }),
    ];
    const sorted = sortChecksByStatusSeverity(checks);
    expect(sorted.map((c) => c.check_code)).toEqual(["LATE_ARRIVAL_RATE", "SUBJECT_UNKNOWN_RATE"]);
  });

  it("does not mutate the input array", () => {
    const checks = [check({ check_code: "b", status: "OK" }), check({ check_code: "a", status: "FAIL" })];
    const copy = [...checks];
    sortChecksByStatusSeverity(checks);
    expect(checks).toEqual(copy);
  });

  it("labels every status in Korean", () => {
    expect(dataQualityCheckStatusLabel("OK")).toBe("정상");
    expect(dataQualityCheckStatusLabel("WARN")).toBe("경고");
    expect(dataQualityCheckStatusLabel("FAIL")).toBe("실패");
  });

  it("thresholdRatio returns null when either value is unobserved (never fabricates 0/1)", () => {
    expect(thresholdRatio(check({ metric_value: null, threshold_value: 10 }))).toBeNull();
    expect(thresholdRatio(check({ metric_value: 5, threshold_value: null }))).toBeNull();
  });

  it("thresholdRatio computes metric/threshold when both are observed", () => {
    expect(thresholdRatio(check({ metric_value: 15, threshold_value: 10 }))).toBe(1.5);
  });
});
