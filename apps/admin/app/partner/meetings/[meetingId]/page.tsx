"use client";

/**
 * 참가업체 포털 - 상담 상세 (E-03/E-04). 바이어 요약 조회, 수락/거절/시간재제안, 결과기록.
 *
 * candidate_slots는 단건 조회 API가 없어 목록에서 찾는다
 * (features/partner-meeting/api.ts `findPartnerMeetingListItem`, types.ts 계약 공백 2 참고).
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";

import { findPartnerMeetingListItem, getPartnerBuyerSummary } from "@/features/partner-meeting/api";
import BuyerSummaryPanel from "@/features/partner-meeting/components/BuyerSummaryPanel";
import DecisionPanel from "@/features/partner-meeting/components/DecisionPanel";
import MeetingStatusBadge from "@/features/partner-meeting/components/MeetingStatusBadge";
import OutcomePanel from "@/features/partner-meeting/components/OutcomePanel";
import type {
  PartnerBuyerSummaryResponse,
  PartnerMeetingListItem,
} from "@/features/partner-meeting/types";

export default function PartnerMeetingDetailPage() {
  const params = useParams<{ meetingId: string }>();
  const meetingId = params.meetingId;
  const [summary, setSummary] = useState<PartnerBuyerSummaryResponse | null>(null);
  const [listItem, setListItem] = useState<PartnerMeetingListItem | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    if (!meetingId) return;
    setLoading(true);
    setError(null);
    Promise.all([getPartnerBuyerSummary(meetingId), findPartnerMeetingListItem(meetingId)])
      .then(([summaryRes, itemRes]) => {
        setSummary(summaryRes);
        setListItem(itemRes);
      })
      .catch((err) => setError(err))
      .finally(() => setLoading(false));
  }, [meetingId]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <Link href="/partner/meetings" className="text-sm text-[var(--color-brand)] underline">
            ← 상담 요청함
          </Link>
          <h1 className="mt-1 text-xl font-semibold">상담 상세</h1>
          <p className="font-mono text-xs text-[var(--color-text-muted)]">{meetingId}</p>
        </div>
        {summary && <MeetingStatusBadge status={summary.status} />}
      </div>

      {loading && <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>}
      {error ? <ErrorBanner error={error} onRetry={load} /> : null}

      {summary && (
        <>
          <BuyerSummaryPanel summary={summary} />

          {!listItem && (
            <p className="text-xs text-[var(--color-warning)]">
              TODO(BACKEND-MEETING): 이 상담의 후보 시간 슬롯(candidate_slots)을 최근 목록
              5페이지(최대 250건) 안에서 찾지 못했습니다. 참가업체 포털에 단건 조회 API
              (GET /partner/meetings/&#123;id&#125;)가 없어 목록을 스캔하는 임시 구현입니다 -
              아래 응답 폼에서 시간 슬롯 ID를 직접 입력해 주세요.
            </p>
          )}

          <DecisionPanel
            meetingId={meetingId}
            status={summary.status}
            candidateSlots={listItem?.candidate_slots ?? []}
            onDecided={() => load()}
          />

          <OutcomePanel meetingId={meetingId} status={summary.status} onRecorded={() => load()} />
        </>
      )}
    </div>
  );
}
