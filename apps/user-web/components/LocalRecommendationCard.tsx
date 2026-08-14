"use client";

import { useState } from "react";

import type { LocalRecommendationPreview } from "@/lib/personalization-preview";

export default function LocalRecommendationCard({
  item,
  rank,
}: {
  item: LocalRecommendationPreview;
  rank: number;
}) {
  const [saved, setSaved] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) {
    return (
      <div className="backju-panel border p-4 text-sm" role="status" style={{ borderColor: "var(--color-border)" }}>
        관심 없음으로 반영했습니다. 이 화면에서는 해당 업체를 숨깁니다.
      </div>
    );
  }

  return (
    <article className="recommendation-card border p-4" style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}>
      <span className="recommendation-rank" aria-label={`추천 순위 ${rank}위`}>
        <span aria-hidden="true">MATCH</span>
        <strong>{String(rank).padStart(2, "0")}</strong>
      </span>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="text-base font-extrabold">{item.exhibitorName}</h3>
          <p className="mt-0.5 text-sm font-semibold" style={{ color: "var(--color-brand)" }}>
            {item.matchLabel}
          </p>
        </div>
        <span className="rounded-full border px-2 py-1 text-xs font-bold" style={{ borderColor: "var(--color-border)" }}>
          {item.categoryLabel}
        </span>
      </div>
      <p className="mt-2 text-sm" style={{ color: "var(--color-text-muted)" }}>
        {item.productName} · {item.boothLabel}
      </p>
      <ul className="recommendation-reasons mt-3 space-y-1">
        {item.reasons.map((reason) => (
          <li key={reason} className="text-sm">· {reason}</li>
        ))}
      </ul>
      <p className="mt-3 inline-flex rounded-full bg-[#f4efe3] px-2.5 py-1 text-xs font-bold text-[#67573d]">
        {item.informationStatus}
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          aria-pressed={saved}
          onClick={() => setSaved((value) => !value)}
          className="tap-target rounded-full border px-4 text-sm font-bold"
          style={{ borderColor: saved ? "var(--color-brand)" : "var(--color-border)", color: saved ? "var(--color-brand)" : undefined }}
        >
          {saved ? "관심 저장됨" : "관심 저장"}
        </button>
        <button
          type="button"
          onClick={() => setDismissed(true)}
          className="tap-target rounded-full border px-4 text-sm font-semibold"
          style={{ borderColor: "var(--color-border)", color: "var(--color-text-muted)" }}
        >
          관심 없음
        </button>
      </div>
    </article>
  );
}
