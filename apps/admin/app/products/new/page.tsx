"use client";

/**
 * 제품 등록 폼 (작업 지시 필수 요구사항).
 * 실제로 동작하는 `POST /partner/products`(08 28.3절, apps/api/app/api/v1/routers/partner.py)
 * 를 호출한다. exhibitor_id 소속 EXHIBITOR 또는 OPERATOR/ADMIN 역할이 있어야 성공한다.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { createProduct } from "@/lib/api-client";
import type { ProductRead } from "@/lib/types";
import ErrorBanner from "@/components/ErrorBanner";
import Field from "@/components/Field";

export default function NewProductPage() {
  const router = useRouter();
  const [exhibitorId, setExhibitorId] = useState("");
  const [eventId, setEventId] = useState("");
  const [productName, setProductName] = useState("");
  const [productSummary, setProductSummary] = useState("");
  const [alcoholPercentage, setAlcoholPercentage] = useState("");
  const [productionMethod, setProductionMethod] = useState("");
  const [mainIngredients, setMainIngredients] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [created, setCreated] = useState<ProductRead | null>(null);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    setCreated(null);
    try {
      const product = await createProduct({
        exhibitor_id: exhibitorId,
        event_id: eventId || null,
        product_name: productName,
        product_summary: productSummary || null,
        alcohol_percentage: alcoholPercentage ? Number(alcoholPercentage) : null,
        production_method: productionMethod || null,
        main_ingredients: mainIngredients
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      });
      setCreated(product);
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex max-w-2xl flex-col gap-4">
      <h1 className="text-xl font-semibold">제품 등록</h1>
      <p className="text-sm text-[var(--color-text-muted)]">
        <code>POST /partner/products</code>를 호출합니다(실제 동작). 등록 직후 승인상태는
        DRAFT이며, 업체 검수 제출·운영자 승인을 거쳐야 검색·추천에 노출됩니다(§28절).
      </p>

      {error ? <ErrorBanner error={error} /> : null}
      {created && (
        <div className="rounded-lg border border-[var(--color-success)] bg-[var(--color-success-bg)] p-4 text-sm text-[var(--color-success)]">
          <p className="font-semibold">등록 완료: {created.product_name}</p>
          <p>product_id: {created.product_id}</p>
          <button
            type="button"
            onClick={() => router.push(`/products/${created.product_id}/edit`)}
            className="tap-target mt-2 rounded-md border border-current px-3 py-1.5 text-xs font-medium"
          >
            거래조건 등록하러 가기
          </button>
        </div>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
        className="flex flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4"
      >
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="업체 ID" required hint="UUID">
            <input required value={exhibitorId} onChange={(e) => setExhibitorId(e.target.value)} className="input font-mono text-xs" />
          </Field>
          <Field label="행사 ID" hint="지정하면 해당 행사 전시제품으로도 등록됩니다">
            <input value={eventId} onChange={(e) => setEventId(e.target.value)} className="input font-mono text-xs" />
          </Field>
        </div>

        <Field label="제품명" required>
          <input required value={productName} onChange={(e) => setProductName(e.target.value)} className="input" />
        </Field>

        <Field label="제품 소개">
          <textarea value={productSummary} onChange={(e) => setProductSummary(e.target.value)} className="input" rows={3} />
        </Field>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="알코올 도수(%)">
            <input
              type="number"
              min={0}
              max={100}
              step="0.1"
              value={alcoholPercentage}
              onChange={(e) => setAlcoholPercentage(e.target.value)}
              className="input"
            />
          </Field>
          <Field label="제조방식">
            <input value={productionMethod} onChange={(e) => setProductionMethod(e.target.value)} className="input" />
          </Field>
        </div>

        <Field label="주요 원재료" hint="쉼표(,)로 구분">
          <input value={mainIngredients} onChange={(e) => setMainIngredients(e.target.value)} className="input" />
        </Field>

        <button
          type="submit"
          disabled={submitting}
          className="tap-target w-fit rounded-md bg-[var(--color-brand)] px-4 py-2 text-sm font-medium text-[var(--color-brand-contrast)] disabled:opacity-50"
        >
          {submitting ? "등록 중…" : "등록"}
        </button>
      </form>
    </div>
  );
}
