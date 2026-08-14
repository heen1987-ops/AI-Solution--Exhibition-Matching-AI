"use client";

/**
 * A04 업체 검수 (작업 지시 필수 요구사항: 업체 승인/반려(반려 시 사유 필수), 변경 전후 값
 * 비교 표시, 역할별 버튼 노출 제어).
 *
 * 데이터 출처가 두 갈래로 나뉜다:
 *   - "실제 구현됨": GET /exhibitors/{id}/profile (partner.py) - 현재(after) 값.
 *     POST /partner/exhibitors/{id}/submit - 업체 담당자의 검수 제출.
 *   - "TODO 미구현": GET /admin/exhibitors/review/{id} - 이전 버전(before)·AI 추출 근거·
 *     review_status. POST /admin/exhibitors/{id}/approve|reject - 승인/반려.
 *     (.harness/decisions.md DECISION-005, backlog BACKEND-007)
 * 미구현 API는 실패하면 명확한 오류로 보여주고, 실제 프로파일 데이터는 그와 별개로 정상
 * 표시한다 - 한 API의 실패가 다른 실제 데이터 표시를 막지 않는다.
 */

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  ApiClientError,
  approveExhibitor,
  getExhibitorProfile,
  getExhibitorReviewDetail,
  rejectExhibitor,
  submitExhibitorForReview,
} from "@/lib/api-client";
import type {
  AdminExhibitorDetail,
  ExhibitorProfileRead,
  SubmitResponse,
} from "@/lib/types";
import DiffTable, { type DiffRow } from "@/components/DiffTable";
import ErrorBanner from "@/components/ErrorBanner";
import RoleGate from "@/components/RoleGate";
import StatusBadge from "@/components/StatusBadge";

export default function ExhibitorReviewPage() {
  const params = useParams<{ exhibitorId: string }>();
  const router = useRouter();
  const exhibitorId = params.exhibitorId;

  const [profile, setProfile] = useState<ExhibitorProfileRead | null>(null);
  const [profileError, setProfileError] = useState<unknown>(null);
  const [profileLoading, setProfileLoading] = useState(true);

  const [reviewDetail, setReviewDetail] = useState<AdminExhibitorDetail | null>(null);
  const [reviewError, setReviewError] = useState<unknown>(null);
  const [reviewLoading, setReviewLoading] = useState(true);

  const loadProfile = useCallback(() => {
    setProfileLoading(true);
    setProfileError(null);
    getExhibitorProfile(exhibitorId)
      .then(setProfile)
      .catch((err) => setProfileError(err))
      .finally(() => setProfileLoading(false));
  }, [exhibitorId]);

  const loadReviewDetail = useCallback(() => {
    setReviewLoading(true);
    setReviewError(null);
    getExhibitorReviewDetail(exhibitorId)
      .then(setReviewDetail)
      .catch((err) => setReviewError(err))
      .finally(() => setReviewLoading(false));
  }, [exhibitorId]);

  useEffect(() => {
    loadProfile();
    loadReviewDetail();
  }, [loadProfile, loadReviewDetail]);

  const diffRows: DiffRow[] | null = profile
    ? [
        { label: "업체명", before: reviewDetail?.previous_version?.company_name ?? null, after: profile.company_name },
        {
          label: "업체소개",
          before: reviewDetail?.previous_version?.company_summary ?? null,
          after: profile.company_summary,
        },
        {
          label: "웹사이트",
          before: reviewDetail?.previous_version?.website_url ?? null,
          after: profile.website_url,
        },
        {
          label: "완성도(%)",
          before: reviewDetail?.previous_version?.data_completeness_percent ?? null,
          after: profile.data_completeness_percent,
        },
        {
          label: "승인상태",
          before: reviewDetail?.previous_version?.master_approval_status ?? null,
          after: profile.master_approval_status,
        },
      ]
    : null;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">업체 검수</h1>
        <button
          type="button"
          onClick={() => router.push("/exhibitors")}
          className="tap-target text-sm text-[var(--color-brand)] underline"
        >
          목록으로
        </button>
      </div>

      {profileLoading && <p className="text-sm text-[var(--color-text-muted)]">업체 정보를 불러오는 중…</p>}
      {!profileLoading && profileError ? <ErrorBanner error={profileError} onRetry={loadProfile} /> : null}

      {!profileLoading && !profileError && profile && (
        <>
          <section className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold">{profile.company_name}</h2>
              <StatusBadge status={profile.master_approval_status} />
              {profile.supply_profile && <StatusBadge status={profile.supply_profile.approval_status} />}
            </div>
            <dl className="mt-3 grid grid-cols-1 gap-2 text-sm md:grid-cols-2">
              <div>
                <dt className="text-[var(--color-text-muted)]">업체소개</dt>
                <dd>{profile.company_summary ?? "(없음)"}</dd>
              </div>
              <div>
                <dt className="text-[var(--color-text-muted)]">웹사이트</dt>
                <dd>{profile.website_url ?? "(없음)"}</dd>
              </div>
              <div>
                <dt className="text-[var(--color-text-muted)]">필수정보 완성도</dt>
                <dd>{profile.data_completeness_percent}%</dd>
              </div>
              <div>
                <dt className="text-[var(--color-text-muted)]">프로파일 버전</dt>
                <dd>v{profile.current_profile_version}</dd>
              </div>
            </dl>
            {profile.supply_profile && (
              <p className="mt-3 text-xs text-[var(--color-text-muted)]">
                소비자용 완성도 {profile.supply_profile.consumer_completeness}% · 바이어용 완성도{" "}
                {profile.supply_profile.buyer_completeness}%
              </p>
            )}
          </section>

          <section>
            <h2 className="mb-2 text-base font-semibold">변경 전후 값 비교</h2>
            {reviewLoading && <p className="text-sm text-[var(--color-text-muted)]">검수 상세를 불러오는 중…</p>}
            {!reviewLoading && reviewError ? (
              <div className="flex flex-col gap-2">
                <ErrorBanner error={reviewError} onRetry={loadReviewDetail} />
                <p className="text-xs text-[var(--color-text-muted)]">
                  변경 이력(이전 버전) API가 없어 지금은 현재 값만 확인할 수 있습니다. 아래
                  표의 ‘변경 전’ 칸은 그 API가 구현되기 전까지 비어 있습니다.
                </p>
              </div>
            ) : null}
            {diffRows && <DiffTable rows={diffRows} caption="변경 전 = 승인된 직전 버전(TODO), 변경 후 = 현재 값" />}
          </section>

          {reviewDetail && reviewDetail.ai_extractions.length > 0 && (
            <section>
              <h2 className="mb-2 text-base font-semibold">AI 추출 근거 (§29절)</h2>
              <ul className="flex flex-col gap-2">
                {reviewDetail.ai_extractions.map((field) => (
                  <li
                    key={field.field}
                    className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3 text-sm"
                  >
                    <p className="font-medium">{field.field}</p>
                    <p className="text-[var(--color-text-muted)]">AI 제안값: {String(field.ai_value)}</p>
                    <p className="mt-1 text-xs italic">근거: {field.evidence_text ?? "(근거 없음)"}</p>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <ReviewActions exhibitorId={exhibitorId} onDecided={() => { loadProfile(); loadReviewDetail(); }} />

          <SubmitAction exhibitorId={exhibitorId} onSubmitted={loadProfile} />
        </>
      )}
    </div>
  );
}

function ReviewActions({
  exhibitorId,
  onDecided,
}: {
  exhibitorId: string;
  onDecided: () => void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [decidedMessage, setDecidedMessage] = useState<string | null>(null);

  const approve = async () => {
    setBusy("approve");
    setError(null);
    setDecidedMessage(null);
    try {
      const res = await approveExhibitor(exhibitorId, {});
      setDecidedMessage(`승인 처리되었습니다 (${res.decided_at}).`);
      onDecided();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  };

  const reject = async () => {
    setBusy("reject");
    setError(null);
    setDecidedMessage(null);
    try {
      // apps/admin/lib/api-client.ts의 rejectExhibitor가 reason 공백을 클라이언트에서부터
      // 막는다 - 작업 지시 "반려 시 사유 필수 입력"을 네트워크 호출 이전에 강제한다.
      const res = await rejectExhibitor(exhibitorId, { reason });
      setDecidedMessage(`반려 처리되었습니다 (${res.decided_at}).`);
      setReason("");
      onDecided();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  };

  return (
    <RoleGate
      capability="EXHIBITOR_APPROVE"
      fallback={
        <p className="text-sm text-[var(--color-text-muted)]">
          현재 역할(자사 초안·제출만 가능)에는 승인/반려 권한이 없습니다.
        </p>
      }
    >
      <section className="flex flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <h2 className="text-base font-semibold">승인 / 반려</h2>
        {error ? <ErrorBanner error={error} /> : null}
        {decidedMessage && (
          <p className="rounded-md border border-[var(--color-success)] bg-[var(--color-success-bg)] p-2 text-sm text-[var(--color-success)]">
            {decidedMessage}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void approve()}
            disabled={busy !== null}
            className="tap-target rounded-md bg-[var(--color-success)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy === "approve" ? "승인 처리 중…" : "승인"}
          </button>
        </div>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">
            반려 사유 <span className="text-[var(--color-danger)]">*</span>
          </span>
          <textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className="input"
            rows={2}
            placeholder="반려 사유를 입력해야 반려 버튼이 활성화됩니다."
          />
        </label>
        <button
          type="button"
          onClick={() => void reject()}
          disabled={busy !== null || !reason.trim()}
          className="tap-target w-fit rounded-md bg-[var(--color-danger)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy === "reject" ? "반려 처리 중…" : "반려"}
        </button>
      </section>
    </RoleGate>
  );
}

function SubmitAction({
  exhibitorId,
  onSubmitted,
}: {
  exhibitorId: string;
  onSubmitted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<SubmitResponse | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await submitExhibitorForReview(exhibitorId);
      setResult(res);
      onSubmitted();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <RoleGate capability="EXHIBITOR_SUBMIT_OWN">
      <section className="flex flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <h2 className="text-base font-semibold">검수 제출</h2>
        <p className="text-xs text-[var(--color-text-muted)]">
          <code>POST /partner/exhibitors/{"{id}"}/submit</code> (실제 동작). 필수정보가
          부족하면 <code>PROFILE_INCOMPLETE</code> 오류와 blocking_issues 목록을 그대로
          보여줍니다.
        </p>
        {error ? (
          <>
            <ErrorBanner error={error} />
            {error instanceof ApiClientError && error.code === "PROFILE_INCOMPLETE" && (
              <p className="text-xs text-[var(--color-danger)]">
                제출 차단 사유: {error.field_errors.map((f) => f.reason).join(", ") || "확인 필요"}
              </p>
            )}
          </>
        ) : null}
        {result && (
          <div className="rounded-md border border-[var(--color-success)] bg-[var(--color-success-bg)] p-2 text-sm text-[var(--color-success)]">
            제출 완료: {result.approval_status} (소비자 완성도 {result.consumer_completeness}%,
            바이어 완성도 {result.buyer_completeness}%)
          </div>
        )}
        <button
          type="button"
          onClick={() => void submit()}
          disabled={busy}
          className="tap-target w-fit rounded-md bg-[var(--color-brand)] px-4 py-2 text-sm font-medium text-[var(--color-brand-contrast)] disabled:opacity-50"
        >
          {busy ? "제출 중…" : "검수 제출"}
        </button>
      </section>
    </RoleGate>
  );
}
