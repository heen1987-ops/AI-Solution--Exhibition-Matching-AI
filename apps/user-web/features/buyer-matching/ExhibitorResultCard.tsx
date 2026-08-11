"use client";

/**
 * 바이어 매칭 결과 카드.
 *
 * 요구사항 (작업 지시 원문)
 * --------------------------
 * "exhibitor result cards showing grade (HIGH/MEDIUM/POSSIBLE) + human-readable reason,
 * info needed fields clearly marked, compare-up-to-4 button, save-to-favorites,
 * request-meeting CTA."
 *
 * 상담 요청 CTA는 `features/buyer-profile`의 인증상태 판정(`canRequestMeeting`)을 그대로
 * 재사용해 게이팅한다 - 미인증 바이어가 상담을 요청하면 어차피 백엔드가 막겠지만, 화면
 * 단계에서 먼저 이유를 설명하는 게 더 나은 경험이다(막연히 실패하는 것보다).
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { ApiClientError, createFavorite, deleteFavorite, postInteraction } from "@/lib/api-client";

import { canRequestMeeting } from "@/features/buyer-profile/VerificationStatusBanner";
import type { BuyerVerificationStatus } from "@/features/buyer-profile/types";
import { useComparisonSelection } from "@/features/exhibitor-comparison/comparison-selection";

import { GRADE_LABEL, GRADE_TONE, type MatchingCardData } from "./types";

const TONE_COLORS = {
  positive: { fg: "var(--color-success)", bg: "color-mix(in srgb, var(--color-success) 14%, transparent)" },
  info: { fg: "var(--color-brand)", bg: "color-mix(in srgb, var(--color-brand) 12%, transparent)" },
  neutral: { fg: "var(--color-text-muted)", bg: "color-mix(in srgb, var(--color-text-muted) 14%, transparent)" },
} as const;

export interface ExhibitorResultCardProps {
  data: MatchingCardData;
  verificationStatus: BuyerVerificationStatus;
  recommendationSessionId?: string | null;
  initialFavoriteId?: string | null;
}

export default function ExhibitorResultCard({
  data,
  verificationStatus,
  recommendationSessionId,
  initialFavoriteId = null,
}: ExhibitorResultCardProps) {
  const { item, grade, exhibitor, exhibitorLoadFailed, infoNeededFields } = data;
  const comparison = useComparisonSelection();
  const [favoriteId, setFavoriteId] = useState<string | null>(initialFavoriteId);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [compareMessage, setCompareMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!compareMessage) return;
    const timer = setTimeout(() => setCompareMessage(null), 3000);
    return () => clearTimeout(timer);
  }, [compareMessage]);

  const tone = GRADE_TONE[grade];
  const toneColors = TONE_COLORS[tone];
  const meetingAllowed = canRequestMeeting(verificationStatus);
  const reasons = item.reasons.slice(0, 3);

  async function handleToggleSave() {
    if (saving || !item.exhibitor_id) return;
    setSaving(true);
    setSaveError(null);
    try {
      if (favoriteId) {
        await deleteFavorite(favoriteId);
        setFavoriteId(null);
      } else {
        const favorite = await createFavorite({
          object_type: "EXHIBITOR",
          object_id: item.exhibitor_id,
          source: "RECOMMENDATION",
          match_result_id: item.match_result_id,
        });
        setFavoriteId(favorite.favorite_id);
        void postInteraction({
          event_type: "RECOMMENDATION_SAVED",
          object_type: "EXHIBITOR",
          object_id: item.exhibitor_id,
          recommendation_session_id: recommendationSessionId ?? null,
          match_result_id: item.match_result_id,
          rank_at_event: item.rank,
          screen: "EXPLORE",
          occurred_at: new Date().toISOString(),
        }).catch(() => {});
      }
    } catch (err) {
      setSaveError(err instanceof ApiClientError ? err.message : "저장하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  }

  function handleToggleCompare() {
    if (!item.exhibitor_id) return;
    const { blockedByLimit } = comparison.toggle(item.exhibitor_id);
    if (blockedByLimit) {
      setCompareMessage("최대 4곳까지만 비교할 수 있어요. 다른 업체를 먼저 빼 주세요.");
    }
  }

  const isComparing = item.exhibitor_id ? comparison.isSelected(item.exhibitor_id) : false;

  return (
    <div
      data-testid="exhibitor-result-card"
      data-grade={grade}
      className="rounded-2xl border p-4"
      style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          {exhibitorLoadFailed ? (
            <p className="text-sm font-semibold" style={{ color: "var(--color-danger)" }}>
              업체 정보를 불러오지 못했어요.
            </p>
          ) : (
            <p className="truncate text-base font-bold">{exhibitor?.company_name ?? "업체 정보 확인 중"}</p>
          )}
          {exhibitor?.company_summary ? (
            <p className="mt-0.5 text-sm" style={{ color: "var(--color-text-muted)" }}>
              {exhibitor.company_summary}
            </p>
          ) : null}
        </div>
        <span
          data-testid="match-grade-badge"
          className="shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold"
          style={{ color: toneColors.fg, backgroundColor: toneColors.bg }}
        >
          {GRADE_LABEL[grade]}
        </span>
      </div>

      {reasons.length > 0 ? (
        <ul className="mt-2 space-y-0.5">
          {reasons.map((reason) => (
            <li key={`${reason.code}-${reason.text}`} className="text-sm">
              · {reason.text}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm" style={{ color: "var(--color-text-muted)" }}>
          추천 이유를 정리하고 있어요.
        </p>
      )}

      {infoNeededFields.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5" aria-label="확인이 더 필요한 정보">
          {infoNeededFields.map((field) => (
            <span
              key={field}
              data-testid="info-needed-chip"
              className="rounded-full border px-2 py-0.5 text-xs font-medium"
              style={{ borderColor: "var(--color-border)", color: "var(--color-text-muted)" }}
            >
              {field} 확인 필요
            </span>
          ))}
        </div>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={handleToggleCompare}
          disabled={!item.exhibitor_id}
          aria-pressed={isComparing}
          className="tap-target rounded-lg border px-3 text-sm font-semibold disabled:opacity-60"
          style={{
            borderColor: isComparing ? "var(--color-brand)" : "var(--color-border)",
            color: isComparing ? "var(--color-brand)" : "var(--color-text)",
          }}
        >
          {isComparing ? `비교함에 담김 (${comparison.selectedIds.length}/4)` : "비교하기"}
        </button>

        <button
          type="button"
          onClick={handleToggleSave}
          disabled={saving || !item.exhibitor_id}
          aria-pressed={Boolean(favoriteId)}
          className="tap-target rounded-lg border px-3 text-sm font-semibold disabled:opacity-60"
          style={{
            borderColor: favoriteId ? "var(--color-brand)" : "var(--color-border)",
            color: favoriteId ? "var(--color-brand)" : "var(--color-text)",
          }}
        >
          {favoriteId ? "저장됨" : "저장"}
        </button>

        {item.exhibitor_id && meetingAllowed ? (
          <Link
            href={`/meetings/new?exhibitorId=${encodeURIComponent(item.exhibitor_id)}`}
            className="tap-target rounded-lg px-3 text-sm font-bold"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
          >
            상담 요청
          </Link>
        ) : (
          <span
            className="tap-target rounded-lg border px-3 text-center text-sm font-semibold"
            style={{ borderColor: "var(--color-border)", color: "var(--color-text-muted)" }}
            title="바이어 인증을 완료하면 상담을 요청할 수 있어요."
          >
            상담 요청(인증 필요)
          </span>
        )}
      </div>

      {saveError ? (
        <p role="alert" className="mt-2 text-xs" style={{ color: "var(--color-danger)" }}>
          {saveError}
        </p>
      ) : null}
      {compareMessage ? (
        <p role="status" aria-live="polite" className="mt-2 text-xs" style={{ color: "var(--color-text-muted)" }}>
          {compareMessage}
        </p>
      ) : null}
    </div>
  );
}
