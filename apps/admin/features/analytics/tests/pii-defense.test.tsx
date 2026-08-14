import "@testing-library/jest-dom/vitest";

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import BuyerSection from "../components/BuyerSection";
import KioskSection from "../components/KioskSection";
import OverviewSection from "../components/OverviewSection";
import WebSection from "../components/WebSection";
import { sanitizeAnalyticsPayload } from "../logic";
import type { BuyerAnalyticsResponse, KioskAnalyticsResponse, OverviewAnalyticsResponse, WebAnalyticsResponse } from "../types";

/**
 * MOST IMPORTANT TEST FILE IN THIS TRACK (per task instruction).
 *
 * Simulates a buggy backend that leaks individual-level PII (name/email/phone/contact) into an
 * analytics response, runs it through the exact pipeline `features/analytics/api.ts` uses
 * (`sanitizeAnalyticsPayload`), and asserts the rendered DOM of every dashboard section contains
 * none of it. This is "defense in depth at the UI layer": even though `apps/api/app/services/
 * analytics/suppression.py` is supposed to prevent this on the backend, this dashboard must not
 * render individual-level PII even if that backend guard fails.
 */

afterEach(() => {
  cleanup();
});

const PII_NAME = "홍길동";
const PII_EMAIL = "leaked-buyer@example.com";
const PII_PHONE = "010-9876-5432";

const okMetric = { value: 42, suppressed: false };

describe("PII never reaches the rendered DOM, even from a buggy backend payload", () => {
  it("OverviewSection", () => {
    const dirty = {
      event_id: "evt-1",
      period_start: "2026-08-01",
      period_end: "2026-08-03",
      role: "EVENT_ADMIN",
      registered_users: okMetric,
      profile_confirm_rate: okMetric,
      web_active_users: okMetric,
      kiosk_sessions: okMetric,
      total_searches: okMetric,
      no_result_rate: okMetric,
      recommendation_click_rate: okMetric,
      favorites_saved: okMetric,
      buyer_matches: okMetric,
      meeting_requests: okMetric,
      meeting_accepts: okMetric,
      published_exhibitor_count: okMetric,
      published_product_count: okMetric,
      // Buggy backend fields that should never exist on this response but might leak anyway.
      top_buyer_contact_email: PII_EMAIL,
      top_buyer_name: PII_NAME,
      admin_phone: PII_PHONE,
    };
    const clean = sanitizeAnalyticsPayload(dirty) as OverviewAnalyticsResponse;
    const { container } = render(<OverviewSection data={clean} />);
    expectNoPii(container.textContent ?? "");
  });

  it("WebSection, including a PII-laced per-interest breakdown row", () => {
    const dirty = {
      event_id: "evt-1",
      period_start: "2026-08-01",
      period_end: "2026-08-03",
      role: "EVENT_ADMIN",
      active_users: okMetric,
      sessions: okMetric,
      avg_session_duration_seconds: okMetric,
      recommendation_impressions: okMetric,
      recommendation_clicks: okMetric,
      recommendation_click_rate: okMetric,
      favorites_saved: okMetric,
      daily_active_users: [{ activity_date: "2026-08-01", count: 3 }],
      profile_funnel: [{ step: `프로파일 시작 (연락처: ${PII_PHONE})`, users: okMetric }],
      per_interest_performance: [
        { concept_code: `FLAVOR.SWEET 문의: ${PII_EMAIL}`, impressions: okMetric, clicks: okMetric, click_rate: okMetric },
      ],
    };
    const clean = sanitizeAnalyticsPayload(dirty) as WebAnalyticsResponse;
    const { container } = render(<WebSection data={clean} />);
    expectNoPii(container.textContent ?? "");
  });

  it("KioskSection, including a PII-laced per-device breakdown row", () => {
    const dirty = {
      event_id: "evt-1",
      period_start: "2026-08-01",
      period_end: "2026-08-03",
      role: "EVENT_ADMIN",
      sessions: okMetric,
      avg_session_duration_seconds: okMetric,
      qr_handoffs: okMetric,
      searches: okMetric,
      zero_result_rate: okMetric,
      daily_sessions: [{ activity_date: "2026-08-01", count: 3 }],
      per_device: [
        {
          kiosk_id: `K-01 (연락처 ${PII_PHONE}, 문의 ${PII_EMAIL})`,
          sessions: okMetric,
          zero_result_rate: okMetric,
        },
      ],
    };
    const clean = sanitizeAnalyticsPayload(dirty) as KioskAnalyticsResponse;
    const { container } = render(<KioskSection data={clean} />);
    const text = container.textContent ?? "";
    expect(text).not.toContain(PII_EMAIL);
    expect(text).not.toContain(PII_PHONE);
    expect(text).not.toMatch(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/);
    expect(text).not.toMatch(/01\d[-.\s]?\d{3,4}[-.\s]?\d{4}/);
    // Explicit framing requirement: this section must state it is not staff/individual performance evaluation.
    expect(text).toContain("성과를 평가");
  });

  it("KNOWN LIMITATION, documented not silently dropped: redactPiiText only strips email/phone-shaped\n" +
    "   text (per its own docstring and the task instruction's literal wording: \"no raw contact\n" +
    "   info/emails/phone numbers\"). It has no general Korean-name detector, because a regex name\n" +
    "   detector would false-positive on legitimate free text (e.g. an exhibitor or concept label\n" +
    "   that happens to contain a common-surname substring) at an unacceptable rate for an admin\n" +
    "   tool. A bare name with no email/phone/forbidden-key attached is therefore NOT redacted by\n" +
    "   this layer today. Structural fields typed as plain identifiers (kiosk_id, exhibitor_id,\n" +
    "   concept_code) are expected to be system-assigned codes, never raw user-entered free text, so\n" +
    "   this gap is not believed reachable in practice - but it is real and worth tightening if a\n" +
    "   future backend ever lets free text flow into one of those fields.", () => {
    const dirty = { per_device: [{ kiosk_id: `기기 담당 ${PII_NAME}`, sessions: okMetric, zero_result_rate: okMetric }] };
    const clean = sanitizeAnalyticsPayload(dirty) as { per_device: KioskAnalyticsResponse["per_device"] };
    expect(clean.per_device?.[0]?.kiosk_id).toContain(PII_NAME);
  });

  it("BuyerSection, including a PII-laced exhibitor breakdown row, and shows no deal-value/contract-outcome figures", () => {
    const dirty: BuyerAnalyticsResponse & Record<string, unknown> = {
      event_id: "evt-1",
      period_start: "2026-08-01",
      period_end: "2026-08-03",
      role: "EVENT_ADMIN",
      exhibitor_id: null,
      buyer_matches: okMetric,
      meeting_requests: okMetric,
      meeting_accepts: okMetric,
      meeting_completions: okMetric,
      valid_leads: okMetric,
      meeting_accept_rate: okMetric,
      meeting_completion_rate: okMetric,
      valid_lead_rate: okMetric,
      breakdown: [
        {
          exhibitor_id: "ex-1",
          buyer_matches: okMetric,
          meeting_requests: okMetric,
          meeting_accepts: okMetric,
        },
      ],
      // Buggy backend leakage: individual buyer contact + a deal-value figure that must never render.
      buyer_contact_email: PII_EMAIL,
      buyer_name: PII_NAME,
      deal_value_krw: 50000000,
      contract_signed: true,
    };
    const clean = sanitizeAnalyticsPayload(dirty) as BuyerAnalyticsResponse;
    const { container } = render(<BuyerSection data={clean} />);
    const text = container.textContent ?? "";
    expectNoPii(text);
    // deal_value_krw/contract_signed are not in BuyerAnalyticsResponse and the component only
    // renders named fields, so they cannot appear structurally; assert the explicit user-facing
    // statement is present too (task instruction: "explicitly NO deal value or contract-outcome").
    expect(text).not.toContain("50000000");
    expect(text).toContain("거래액이나 계약 성과");
  });
});

function expectNoPii(text: string) {
  expect(text).not.toContain(PII_NAME);
  expect(text).not.toContain(PII_EMAIL);
  expect(text).not.toContain(PII_PHONE);
  expect(text).not.toMatch(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/);
  expect(text).not.toMatch(/01\d[-.\s]?\d{3,4}[-.\s]?\d{4}/);
}
