"use client";

/**
 * 제품 수정 - 거래조건 화면 (작업 지시 필수 요구사항).
 *
 * partner.py에는 제품명·요약 등 "제품 마스터"를 고치는 PATCH 엔드포인트가 없다(제품 등록
 * POST만 있음) - TODO(백엔드 확정 후 대조). 대신 실제로 동작하는 08 28.4절
 * `PUT /partner/products/{id}/trade-conditions`(거래조건 전체 교체)는 있어, 이 화면은
 * "제품 수정"을 거래조건 갱신으로 구현한다.
 */

import { useParams } from "next/navigation";
import { useState } from "react";

import { upsertTradeConditions } from "@/lib/api-client";
import type { TradeAvailabilityStatus, TradeConditionRead } from "@/lib/types";
import ErrorBanner from "@/components/ErrorBanner";
import Field from "@/components/Field";

const AVAILABILITY_OPTIONS: TradeAvailabilityStatus[] = [
  "YES",
  "NO",
  "CONDITIONAL",
  "NEGOTIABLE",
  "UNKNOWN",
];

export default function EditProductTradeConditionsPage() {
  const params = useParams<{ productId: string }>();
  const productId = params.productId;

  const [eventId, setEventId] = useState("");
  const [minOrderQuantity, setMinOrderQuantity] = useState("");
  const [maxOrderQuantity, setMaxOrderQuantity] = useState("");
  const [wholesaleMin, setWholesaleMin] = useState("");
  const [wholesaleMax, setWholesaleMax] = useState("");
  const [currency, setCurrency] = useState("KRW");
  const [oemStatus, setOemStatus] = useState<TradeAvailabilityStatus>("UNKNOWN");
  const [privateLabelStatus, setPrivateLabelStatus] = useState<TradeAvailabilityStatus>("UNKNOWN");
  const [exportStatus, setExportStatus] = useState<TradeAvailabilityStatus>("UNKNOWN");
  const [leadTimeDays, setLeadTimeDays] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState<TradeConditionRead | null>(null);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    setSaved(null);
    try {
      const result = await upsertTradeConditions(productId, {
        event_id: eventId,
        min_order_quantity: minOrderQuantity ? Number(minOrderQuantity) : null,
        max_order_quantity: maxOrderQuantity ? Number(maxOrderQuantity) : null,
        wholesale_price_min_amount: wholesaleMin ? Number(wholesaleMin) : null,
        wholesale_price_max_amount: wholesaleMax ? Number(wholesaleMax) : null,
        currency,
        oem_status: oemStatus,
        private_label_status: privateLabelStatus,
        export_status: exportStatus,
        lead_time_days: leadTimeDays ? Number(leadTimeDays) : null,
      });
      setSaved(result);
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex max-w-2xl flex-col gap-4">
      <h1 className="text-xl font-semibold">제품 수정 - 거래조건</h1>
      <p className="text-sm text-[var(--color-text-muted)]">
        product_id: <code>{productId}</code> · <code>PUT /partner/products/&#123;id&#125;/trade-conditions</code>{" "}
        (실제 동작, 전체 교체).
      </p>

      {error ? <ErrorBanner error={error} /> : null}
      {saved && (
        <p className="rounded-md border border-[var(--color-success)] bg-[var(--color-success-bg)] p-2 text-sm text-[var(--color-success)]">
          저장되었습니다. 승인상태: {saved.approval_status}
        </p>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
        className="flex flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4"
      >
        <Field label="행사 ID" required hint="UUID">
          <input required value={eventId} onChange={(e) => setEventId(e.target.value)} className="input font-mono text-xs" />
        </Field>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="최소 주문수량">
            <input type="number" min={0} value={minOrderQuantity} onChange={(e) => setMinOrderQuantity(e.target.value)} className="input" />
          </Field>
          <Field label="최대 주문수량">
            <input type="number" min={0} value={maxOrderQuantity} onChange={(e) => setMaxOrderQuantity(e.target.value)} className="input" />
          </Field>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Field label="도매가 하한">
            <input type="number" min={0} value={wholesaleMin} onChange={(e) => setWholesaleMin(e.target.value)} className="input" />
          </Field>
          <Field label="도매가 상한">
            <input type="number" min={0} value={wholesaleMax} onChange={(e) => setWholesaleMax(e.target.value)} className="input" />
          </Field>
          <Field label="통화">
            <input value={currency} onChange={(e) => setCurrency(e.target.value)} className="input" maxLength={3} />
          </Field>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Field label="OEM 가능여부">
            <select value={oemStatus} onChange={(e) => setOemStatus(e.target.value as TradeAvailabilityStatus)} className="input">
              {AVAILABILITY_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>{opt}</option>
              ))}
            </select>
          </Field>
          <Field label="PB 가능여부">
            <select value={privateLabelStatus} onChange={(e) => setPrivateLabelStatus(e.target.value as TradeAvailabilityStatus)} className="input">
              {AVAILABILITY_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>{opt}</option>
              ))}
            </select>
          </Field>
          <Field label="수출 가능여부">
            <select value={exportStatus} onChange={(e) => setExportStatus(e.target.value as TradeAvailabilityStatus)} className="input">
              {AVAILABILITY_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>{opt}</option>
              ))}
            </select>
          </Field>
        </div>

        <Field label="리드타임(일)">
          <input type="number" min={0} value={leadTimeDays} onChange={(e) => setLeadTimeDays(e.target.value)} className="input max-w-[160px]" />
        </Field>

        <button
          type="submit"
          disabled={submitting}
          className="tap-target w-fit rounded-md bg-[var(--color-brand)] px-4 py-2 text-sm font-medium text-[var(--color-brand-contrast)] disabled:opacity-50"
        >
          {submitting ? "저장 중…" : "저장"}
        </button>
      </form>
    </div>
  );
}
