/**
 * E-03 바이어 상세 - 상담 확정 전에는 제한된 요약(사업자유형/희망가격/희망물량/결정시기/
 * 요청메모)만 보여주고 연락처는 절대 그리지 않는다(작업 지시 핵심 요구사항).
 */

import { shouldRevealContact } from "../logic";
import type { PartnerBuyerSummaryResponse } from "../types";

function formatRange(
  min: number | null | undefined,
  max: number | null | undefined,
  suffix = "",
): string {
  if (min == null && max == null) return "-";
  const minText = min != null ? min.toLocaleString("ko-KR") : "-";
  const maxText = max != null ? max.toLocaleString("ko-KR") : "-";
  return `${minText} ~ ${maxText}${suffix}`;
}

export default function BuyerSummaryPanel({
  summary,
}: {
  summary: PartnerBuyerSummaryResponse;
}) {
  const revealContact = shouldRevealContact(summary);
  const need = summary.buyer_need;

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <h2 className="text-base font-semibold">바이어 요약 (제한된 정보)</h2>

      <dl className="grid grid-cols-1 gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
        <div className="contents">
          <dt className="text-[var(--color-text-muted)]">상담주제</dt>
          <dd>{summary.topic_code ?? "-"}</dd>
        </div>
        <div className="contents">
          <dt className="text-[var(--color-text-muted)]">사업자 유형</dt>
          <dd>{need?.organization_type ?? "-"}</dd>
        </div>
        <div className="contents">
          <dt className="text-[var(--color-text-muted)]">희망 단가</dt>
          <dd>
            {formatRange(
              need?.target_price_min_amount,
              need?.target_price_max_amount,
              need?.currency ? ` ${need.currency}` : "",
            )}
          </dd>
        </div>
        <div className="contents">
          <dt className="text-[var(--color-text-muted)]">희망 월 물량</dt>
          <dd>{formatRange(need?.monthly_units_min, need?.monthly_units_max)}</dd>
        </div>
        <div className="contents">
          <dt className="text-[var(--color-text-muted)]">결정 시기</dt>
          <dd>{need?.decision_timeline ?? "-"}</dd>
        </div>
        <div className="contents sm:col-span-2">
          <dt className="text-[var(--color-text-muted)]">요청 메모</dt>
          <dd>{summary.message_preview ?? "-"}</dd>
        </div>
      </dl>

      <div className="rounded-md border border-dashed border-[var(--color-border)] p-3">
        <p className="text-sm font-medium">연락처</p>
        {revealContact ? (
          <dl className="mt-1 grid grid-cols-2 gap-1 text-sm">
            {Object.entries(summary.contact ?? {}).map(([field, value]) => (
              <div key={field} className="contents">
                <dt className="text-[var(--color-text-muted)]">{field}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="mt-1 text-xs text-[var(--color-text-muted)]">
            상담이 확정(accepted)되고 바이어가 연락처 공유에 동의해야 표시됩니다. 지금은
            비공개입니다.
          </p>
        )}
      </div>
    </div>
  );
}
