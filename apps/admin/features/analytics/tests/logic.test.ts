import { describe, expect, it } from "vitest";

import {
  buildAggregateCsv,
  canViewAnalyticsSection,
  formatDurationMetric,
  formatMetric,
  freshnessLabel,
  redactPiiText,
  resolveDateRange,
  sanitizeAnalyticsPayload,
  SUPPRESSED_LABEL,
} from "../logic";
import type { Metric } from "../types";

function metric(value: number | null, suppressed = false): Metric {
  return { value, suppressed };
}

describe("resolveDateRange", () => {
  const now = new Date("2026-08-03T10:00:00Z");

  it("TODAY resolves to a single-day range", () => {
    expect(resolveDateRange({ preset: "TODAY", customStart: null, customEnd: null }, null, now)).toEqual({
      periodStart: "2026-08-03",
      periodEnd: "2026-08-03",
    });
  });

  it("LAST_7_DAYS resolves to a 7-day inclusive window ending today", () => {
    const range = resolveDateRange({ preset: "LAST_7_DAYS", customStart: null, customEnd: null }, null, now);
    expect(range.periodEnd).toBe("2026-08-03");
    expect(range.periodStart).toBe("2026-07-28");
  });

  it("EVENT_PERIOD falls back to last 7 days when no event period is known (no event list API yet)", () => {
    const range = resolveDateRange({ preset: "EVENT_PERIOD", customStart: null, customEnd: null }, null, now);
    expect(range).toEqual(resolveDateRange({ preset: "LAST_7_DAYS", customStart: null, customEnd: null }, null, now));
  });

  it("EVENT_PERIOD uses the real event period when known", () => {
    const range = resolveDateRange(
      { preset: "EVENT_PERIOD", customStart: null, customEnd: null },
      { startDate: "2026-09-01", endDate: "2026-09-05" },
      now,
    );
    expect(range).toEqual({ periodStart: "2026-09-01", periodEnd: "2026-09-05" });
  });

  it("CUSTOM uses the given start/end", () => {
    const range = resolveDateRange(
      { preset: "CUSTOM", customStart: "2026-07-01", customEnd: "2026-07-10" },
      null,
      now,
    );
    expect(range).toEqual({ periodStart: "2026-07-01", periodEnd: "2026-07-10" });
  });

  it("CUSTOM swaps start/end when start is after end", () => {
    const range = resolveDateRange(
      { preset: "CUSTOM", customStart: "2026-07-10", customEnd: "2026-07-01" },
      null,
      now,
    );
    expect(range).toEqual({ periodStart: "2026-07-01", periodEnd: "2026-07-10" });
  });

  it("CUSTOM with missing start/end falls back to today", () => {
    const range = resolveDateRange({ preset: "CUSTOM", customStart: null, customEnd: null }, null, now);
    expect(range).toEqual({ periodStart: "2026-08-03", periodEnd: "2026-08-03" });
  });
});

describe("formatMetric (small-group suppression, binding rule)", () => {
  it("shows the suppressed label, never a number, when suppressed=true", () => {
    expect(formatMetric(metric(null, true))).toBe(SUPPRESSED_LABEL);
    // Even if a buggy backend sends both a value and suppressed=true, the label wins.
    expect(formatMetric(metric(3, true))).toBe(SUPPRESSED_LABEL);
  });

  it("formats a normal integer with locale grouping", () => {
    expect(formatMetric(metric(12345))).toBe("12,345");
  });

  it("formats a percent metric", () => {
    expect(formatMetric(metric(0.4567), { percent: true })).toBe("45.7%");
  });

  it("renders a dash for missing metrics (backend has not shipped the field)", () => {
    expect(formatMetric(null)).toBe("—");
    expect(formatMetric(undefined)).toBe("—");
  });
});

describe("formatDurationMetric", () => {
  it("formats seconds as minutes+seconds", () => {
    expect(formatDurationMetric(metric(125))).toBe("2분 5초");
  });

  it("formats sub-minute durations as seconds only", () => {
    expect(formatDurationMetric(metric(42))).toBe("42초");
  });

  it("respects suppression", () => {
    expect(formatDurationMetric(metric(999, true))).toBe(SUPPRESSED_LABEL);
  });
});

describe("redactPiiText", () => {
  it("masks emails", () => {
    expect(redactPiiText("문의: buyer@example.com 로 연락주세요")).toBe("문의: [비공개] 로 연락주세요");
  });

  it("masks Korean mobile numbers with and without separators", () => {
    expect(redactPiiText("010-1234-5678")).toBe("[비공개]");
    expect(redactPiiText("01012345678")).toBe("[비공개]");
  });

  it("does not touch small counts that are not phone-number shaped", () => {
    expect(redactPiiText("검색 12건")).toBe("검색 12건");
  });
});

describe("sanitizeAnalyticsPayload (UI-layer PII double defense)", () => {
  it("strips forbidden keys entirely, even nested inside arrays", () => {
    const dirty = {
      event_id: "evt-1",
      breakdown: [
        { exhibitor_id: "ex-1", buyer_name: "홍길동", contact_phone: "010-1111-2222", buyer_matches: { value: 5, suppressed: false } },
      ],
    };
    const clean = sanitizeAnalyticsPayload(dirty) as typeof dirty;
    expect(clean.breakdown[0]).not.toHaveProperty("buyer_name");
    expect(clean.breakdown[0]).not.toHaveProperty("contact_phone");
    expect(clean.breakdown[0].exhibitor_id).toBe("ex-1");
  });

  it("redacts email/phone-shaped values inside free-text string fields that survive", () => {
    const dirty = { top_interest_codes: [{ concept_code: "FLAVOR.SWEET (문의: a@b.com)", search_count: 3 }] };
    const clean = sanitizeAnalyticsPayload(dirty) as typeof dirty;
    expect(clean.top_interest_codes[0].concept_code).toContain("[비공개]");
    expect(clean.top_interest_codes[0].concept_code).not.toContain("a@b.com");
  });

  it("is a no-op on already-clean aggregate data", () => {
    const clean = { registered_users: { value: 120, suppressed: false }, event_id: "evt-1" };
    expect(sanitizeAnalyticsPayload(clean)).toEqual(clean);
  });
});

describe("buildAggregateCsv", () => {
  it("produces a header + one row per input, structurally scalar-only", () => {
    const csv = buildAggregateCsv([
      { section: "운영 개요", label: "가입자 수", value: "120" },
      { section: "운영 개요", label: "무결과율", value: "5 미만" },
    ]);
    expect(csv).toBe("section,label,value\n운영 개요,가입자 수,120\n운영 개요,무결과율,5 미만");
  });

  it("redacts PII that leaked into a value string before writing the CSV", () => {
    const csv = buildAggregateCsv([{ section: "검색", label: "인기 검색어", value: "buyer@example.com 문의" }]);
    expect(csv).not.toContain("buyer@example.com");
    expect(csv).toContain("[비공개]");
  });

  it("quotes values containing commas", () => {
    const csv = buildAggregateCsv([{ section: "s", label: "l", value: "a,b" }]);
    expect(csv).toContain('"a,b"');
  });
});

describe("freshnessLabel", () => {
  it("prefers the backend-provided data_as_of timestamp", () => {
    const label = freshnessLabel("2026-08-03T09:00:00Z", new Date("2026-08-03T10:00:00Z"));
    expect(label).toContain("데이터 기준");
    expect(label).toContain("집계는 실제 활동보다 지연될 수 있습니다");
  });

  it("falls back to fetch time when data_as_of is absent", () => {
    const label = freshnessLabel(null, new Date("2026-08-03T10:00:00Z"));
    expect(label).toContain("조회 시각 기준");
  });
});

describe("canViewAnalyticsSection (mirrors backend app/services/analytics/access.py)", () => {
  it("EXHIBITOR_ADMIN can only view the buyer section", () => {
    expect(canViewAnalyticsSection("EXHIBITOR_ADMIN", "buyer")).toBe(true);
    expect(canViewAnalyticsSection("EXHIBITOR_ADMIN", "overview")).toBe(false);
    expect(canViewAnalyticsSection("EXHIBITOR_ADMIN", "web")).toBe(false);
    expect(canViewAnalyticsSection("EXHIBITOR_ADMIN", "kiosk")).toBe(false);
  });

  it("EVENT_ADMIN and DATA_REVIEWER can view every section", () => {
    for (const role of ["EVENT_ADMIN", "DATA_REVIEWER"] as const) {
      for (const section of ["overview", "web", "kiosk", "buyer"] as const) {
        expect(canViewAnalyticsSection(role, section)).toBe(true);
      }
    }
  });
});
