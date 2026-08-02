"use client";

/**
 * U-15 상담 상태·확정 (`/meetings/{meetingId}`).
 *
 * 근거 문서
 * ---------
 * - docs/user-ia-wireframes.md 7절 U-15: "`업체 확인 중`, `시간 변경 제안`, `확정`, `거절`,
 *   `취소`, `완료`를 하나의 상태 화면에서 처리한다. 확정 화면에는 업체·시간·부스·주제와
 *   지도·변경·취소 액션을 제공한다."
 * - docs/user-ia-wireframes.md 6.2절(상담 상태모델): `draft → requested → accepted →
 *   completed`, `counter_proposed → accepted`, `rejected`, `cancelled`, `no_show`. "모든
 *   전이에는 행위자, 시각, 이전·이후 상태, 사유를 남긴다. `requested` 이후 중복 제출은 동일
 *   멱등 키로 같은 결과를 반환한다."
 * - docs/frontend-backend-ai-interface-spec.md 12.1절(실제 상태값):
 *   `DRAFT → REQUESTED → CONFIRMED → COMPLETED`, `COUNTER_PROPOSED → CONFIRMED`, `REJECTED`,
 *   `CANCELLED_BY_BUYER`, `CANCELLED_BY_EXHIBITOR`, `NO_SHOW`. 12.4절: 낙관적 잠금 충돌은
 *   `409 MEETING_VERSION_CONFLICT`.
 * - frontend/lib/api-client.ts `getMeeting`/`patchMeetingRequest` 그대로 사용
 *   (`patchMeetingRequest`는 취소는 `POST /meetings/{id}/cancel`, 응답은
 *   `POST /meetings/{id}/respond`로 내부 위임한다).
 *
 * 계약상 제약: 인터페이스 명세 12절에는 바이어가 확정된 상담의 "시간을 다시 제안"하는
 * 엔드포인트가 없다(업체만 `COUNTER_PROPOSE`할 수 있다, 12.4절). 그래서 확정 화면의 "변경"은
 * 실제로 동작하지 않는 버튼을 만드는 대신 안내 문구 + 취소 액션으로 대체했다
 * (TODO: 상담 변경 요청 API가 추가되면 실제 버튼으로 교체).
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import { ApiClientError, getMeeting, patchMeetingRequest } from "@/lib/api-client";
import { enqueueTask, useIsOnline, useOfflineFlush } from "@/lib/offline-queue";
import type { MeetingRequestPatch, MeetingResponse, MeetingStatus } from "@/lib/types";

const STATUS_LABEL: Record<MeetingStatus, string> = {
  DRAFT: "임시 저장",
  REQUESTED: "업체 확인 중",
  CONFIRMED: "확정",
  COMPLETED: "완료",
  COUNTER_PROPOSED: "시간 변경 제안",
  REJECTED: "거절",
  CANCELLED_BY_BUYER: "취소(본인)",
  CANCELLED_BY_EXHIBITOR: "취소(업체)",
  NO_SHOW: "노쇼 처리됨",
};

// U-14와 같은 기본 주제 목록 - 6단계 온톨로지 문서가 없어 잠정 매핑이다.
const TOPIC_LABEL: Record<string, string> = {
  DISTRIBUTION: "입점·유통",
  OEM_PB: "OEM·PB",
  EXPORT: "수출",
  PRODUCT_PRICE: "제품·가격",
  TECH_FACILITY: "기술·설비",
};

const CANCEL_REASON_OPTIONS = [
  { code: "SCHEDULE_CONFLICT", label: "일정이 맞지 않아요" },
  { code: "DECIDED_ELSEWHERE", label: "다른 업체와 진행하기로 했어요" },
  { code: "CHANGED_MIND", label: "단순 변심" },
  { code: "OTHER", label: "기타" },
];

function formatDateTime(iso: string | null): string {
  if (!iso) return "미정";
  const d = new Date(iso);
  return d.toLocaleString("ko-KR", {
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

type QueuedActionPayload = { meetingId: string; patch: MeetingRequestPatch };

export default function MeetingStatusPage() {
  const params = useParams<{ meetingId: string }>();
  const meetingId = params?.meetingId ?? "";
  const router = useRouter();
  const isOnline = useIsOnline();

  const [meeting, setMeeting] = useState<MeetingResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isActing, setIsActing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [showCancelForm, setShowCancelForm] = useState(false);
  const [cancelReason, setCancelReason] = useState<string>(CANCEL_REASON_OPTIONS[0].code);

  const queueKind = `MEETING_ACTION:${meetingId}`;

  const load = useCallback(async () => {
    if (!meetingId) return;
    setLoading(true);
    setLoadError(null);
    try {
      const result = await getMeeting(meetingId);
      setMeeting(result);
    } catch (err) {
      setLoadError(err instanceof ApiClientError ? err.message : "상담 정보를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [meetingId]);

  useEffect(() => {
    void load();
  }, [load]);

  // 6.4절 상태모델: 오프라인 큐에 남은 취소/응답 액션을 온라인 복귀 시 같은 멱등키로 재전송한다.
  useOfflineFlush<QueuedActionPayload>(queueKind, async (payload, key) => {
    const result = await patchMeetingRequest(payload.meetingId, payload.patch, {
      idempotencyKey: key,
    });
    setMeeting(result);
    return { resultId: result.meeting_id };
  });

  async function runAction(patch: MeetingRequestPatch) {
    if (!meeting || isActing) return; // 멱등 제출: 버튼 잠금.
    setIsActing(true);
    setActionError(null);
    setStatusMessage(null);
    const key = `${meetingId}:${patch.kind}:${meeting.row_version}`;
    try {
      const result = await patchMeetingRequest(meetingId, patch, { idempotencyKey: key });
      setMeeting(result);
      setShowCancelForm(false);
      setStatusMessage("처리했습니다.");
    } catch (err) {
      if (err instanceof ApiClientError && err.code === "MEETING_VERSION_CONFLICT") {
        setActionError("상담 정보가 그 사이 바뀌었습니다. 최신 상태로 다시 불러옵니다.");
        await load();
      } else if (err instanceof ApiClientError && (err.code === "NETWORK_ERROR" || err.retryable)) {
        enqueueTask(queueKind, { meetingId, patch }, key);
        setStatusMessage(
          "네트워크에 연결할 수 없어 요청을 저장했습니다. 연결되면 자동으로 다시 시도합니다.",
        );
        setShowCancelForm(false);
      } else if (err instanceof ApiClientError) {
        setActionError(err.message);
      } else {
        setActionError("요청을 처리하지 못했습니다.");
      }
    } finally {
      setIsActing(false);
    }
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-screen-content px-4 py-6">
        <p style={{ color: "var(--color-text-muted)" }}>불러오는 중...</p>
      </div>
    );
  }

  if (loadError || !meeting) {
    return (
      <div className="mx-auto flex max-w-screen-content flex-col gap-3 px-4 py-6">
        <p role="alert" style={{ color: "var(--color-danger)" }}>
          {loadError ?? "상담 정보를 찾을 수 없습니다."}
        </p>
        <button
          type="button"
          onClick={() => void load()}
          className="tap-target self-start rounded-lg border px-4 py-2 text-sm"
          style={{ borderColor: "var(--color-border)" }}
        >
          다시 시도
        </button>
      </div>
    );
  }

  const topicLabel = meeting.topic_code ? TOPIC_LABEL[meeting.topic_code] ?? meeting.topic_code : "주제 미정";

  return (
    <div className="mx-auto flex max-w-screen-content flex-col gap-6 px-4 py-6">
      <header className="flex flex-col gap-1">
        <span
          className="inline-flex w-fit items-center rounded-full px-3 py-1 text-xs font-semibold"
          style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
        >
          {STATUS_LABEL[meeting.status]}
        </span>
        <h1 className="text-xl font-bold">{topicLabel} 상담</h1>
        <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
          업체 ID {meeting.exhibitor_id}
        </p>
      </header>

      {!isOnline ? (
        <p role="status" aria-live="polite" className="text-sm" style={{ color: "var(--color-brand)" }}>
          오프라인 상태입니다. 최근 조회한 상담 정보만 볼 수 있고, 새 요청은 연결되면 전송됩니다.
        </p>
      ) : null}

      {meeting.status === "REQUESTED" ? (
        <section className="flex flex-col gap-3">
          <p>업체가 요청을 확인하고 있어요. 잠시만 기다려 주세요.</p>
          {meeting.candidate_slots.length > 0 ? (
            <ul className="flex flex-col gap-1 text-sm">
              {meeting.candidate_slots.map((slot) => (
                <li key={slot.slot_id}>
                  희망 {formatDateTime(slot.start_at)} ~ {formatDateTime(slot.end_at)}
                </li>
              ))}
            </ul>
          ) : null}
          <CancelControl
            showCancelForm={showCancelForm}
            setShowCancelForm={setShowCancelForm}
            cancelReason={cancelReason}
            setCancelReason={setCancelReason}
            isActing={isActing}
            onConfirmCancel={() =>
              runAction({
                kind: "CANCEL",
                data: { version: meeting.row_version, reason_code: cancelReason },
              })
            }
            confirmLabel="요청 취소"
          />
        </section>
      ) : null}

      {meeting.status === "COUNTER_PROPOSED" ? (
        <section className="flex flex-col gap-3">
          <p>업체가 다른 시간을 제안했어요.</p>
          <ul className="flex flex-col gap-2">
            {meeting.candidate_slots.map((slot) => (
              <li
                key={slot.slot_id}
                className="rounded-lg border p-3 text-sm"
                style={{ borderColor: "var(--color-border)" }}
              >
                {formatDateTime(slot.start_at)} ~ {formatDateTime(slot.end_at)}
                {slot.request_status ? ` · ${slot.request_status}` : ""}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() =>
                runAction({
                  kind: "RESPOND",
                  data: { action: "ACCEPT_COUNTER", version: meeting.row_version },
                })
              }
              disabled={isActing}
              className="tap-target rounded-lg px-5 py-3 text-sm font-semibold disabled:opacity-60"
              style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
            >
              제안 수락
            </button>
            <button
              type="button"
              // TODO(사유 선택 UI 보강): 지금은 고정 사유코드로 거절만 보낸다. 취소와 같은
              // 사유 선택 패턴이 필요하면 CancelControl과 유사한 컴포넌트로 교체한다.
              onClick={() =>
                runAction({
                  kind: "RESPOND",
                  data: { action: "DECLINE", version: meeting.row_version, reason_code: "CHANGED_MIND" },
                })
              }
              disabled={isActing}
              className="tap-target rounded-lg border px-5 py-3 text-sm font-semibold disabled:opacity-60"
              style={{ borderColor: "var(--color-border)" }}
            >
              거절
            </button>
          </div>
        </section>
      ) : null}

      {meeting.status === "CONFIRMED" ? (
        <section className="flex flex-col gap-3">
          <dl
            className="flex flex-col gap-2 rounded-lg border p-4 text-sm"
            style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
          >
            <div className="flex justify-between gap-4">
              <dt style={{ color: "var(--color-text-muted)" }}>시간</dt>
              <dd className="text-right font-medium">
                {formatDateTime(meeting.confirmed_start)} ~ {formatDateTime(meeting.confirmed_end)}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt style={{ color: "var(--color-text-muted)" }}>주제</dt>
              <dd className="text-right font-medium">{topicLabel}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt style={{ color: "var(--color-text-muted)" }}>연락처 공유</dt>
              <dd className="text-right font-medium">
                {meeting.contact_share_accepted
                  ? `공개됨(${meeting.contact_share_fields.join(", ") || "항목 없음"})`
                  : "공유 안 함"}
              </dd>
            </div>
          </dl>
          <div className="flex flex-wrap gap-3">
            <Link
              href={`/route?addType=MEETING&addId=${encodeURIComponent(meeting.meeting_id)}&addLabel=${encodeURIComponent(
                topicLabel + " 상담",
              )}`}
              className="tap-target inline-flex items-center rounded-lg border px-5 py-3 text-sm font-semibold"
              style={{ borderColor: "var(--color-border)" }}
            >
              지도(경로에 추가)
            </Link>
          </div>
          <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
            시간 변경은 아직 지원하지 않습니다. 시간을 바꾸고 싶다면 취소 후 새로 요청해 주세요.
          </p>
          <CancelControl
            showCancelForm={showCancelForm}
            setShowCancelForm={setShowCancelForm}
            cancelReason={cancelReason}
            setCancelReason={setCancelReason}
            isActing={isActing}
            onConfirmCancel={() =>
              runAction({
                kind: "CANCEL",
                data: { version: meeting.row_version, reason_code: cancelReason },
              })
            }
            confirmLabel="상담 취소"
          />
        </section>
      ) : null}

      {meeting.status === "REJECTED" ? (
        <section className="flex flex-col gap-3">
          <p>이번 요청은 업체가 거절했습니다.</p>
          <Link
            href="/explore"
            className="tap-target inline-flex w-fit items-center rounded-lg border px-5 py-3 text-sm font-semibold"
            style={{ borderColor: "var(--color-border)" }}
          >
            다른 업체 둘러보기
          </Link>
        </section>
      ) : null}

      {meeting.status === "CANCELLED_BY_BUYER" || meeting.status === "CANCELLED_BY_EXHIBITOR" ? (
        <section className="flex flex-col gap-3">
          <p>
            {meeting.status === "CANCELLED_BY_BUYER" ? "요청을 취소했습니다." : "업체가 상담을 취소했습니다."}
          </p>
        </section>
      ) : null}

      {meeting.status === "COMPLETED" ? (
        <section className="flex flex-col gap-3">
          <p>상담이 완료되었습니다. 다음 추천에서 후속 부스를 확인해 보세요.</p>
          <Link
            href="/home"
            className="tap-target inline-flex w-fit items-center rounded-lg px-5 py-3 text-sm font-semibold"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
          >
            다음 추천 보기
          </Link>
        </section>
      ) : null}

      {meeting.status === "NO_SHOW" ? (
        <section className="flex flex-col gap-3">
          <p>예정된 시간에 방문이 확인되지 않아 노쇼로 처리되었습니다.</p>
        </section>
      ) : null}

      {meeting.status === "DRAFT" ? (
        <section className="flex flex-col gap-3">
          <p>아직 전송되지 않은 임시 요청입니다.</p>
          <button
            type="button"
            onClick={() => router.push(`/meetings/new?exhibitorId=${encodeURIComponent(meeting.exhibitor_id)}`)}
            className="tap-target w-fit rounded-lg px-5 py-3 text-sm font-semibold"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
          >
            요청 이어서 작성하기
          </button>
        </section>
      ) : null}

      {actionError ? (
        <p role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
          {actionError}
        </p>
      ) : null}
      {statusMessage ? (
        <p role="status" aria-live="polite" className="text-sm" style={{ color: "var(--color-success)" }}>
          {statusMessage}
        </p>
      ) : null}
    </div>
  );
}

function CancelControl({
  showCancelForm,
  setShowCancelForm,
  cancelReason,
  setCancelReason,
  isActing,
  onConfirmCancel,
  confirmLabel,
}: {
  showCancelForm: boolean;
  setShowCancelForm: (v: boolean) => void;
  cancelReason: string;
  setCancelReason: (v: string) => void;
  isActing: boolean;
  onConfirmCancel: () => void;
  confirmLabel: string;
}) {
  if (!showCancelForm) {
    return (
      <button
        type="button"
        onClick={() => setShowCancelForm(true)}
        className="tap-target w-fit rounded-lg border px-5 py-3 text-sm font-semibold"
        style={{ borderColor: "var(--color-border)", color: "var(--color-danger)" }}
      >
        {confirmLabel}
      </button>
    );
  }
  return (
    <div
      className="flex flex-col gap-3 rounded-lg border p-3"
      style={{ borderColor: "var(--color-border)" }}
    >
      <p className="text-sm font-medium">취소 사유를 선택해 주세요</p>
      <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="취소 사유">
        {CANCEL_REASON_OPTIONS.map((option) => (
          <button
            key={option.code}
            type="button"
            role="radio"
            aria-checked={cancelReason === option.code}
            onClick={() => setCancelReason(option.code)}
            className="tap-target rounded-full border px-3 py-2 text-sm"
            style={{
              borderColor: cancelReason === option.code ? "var(--color-brand)" : "var(--color-border)",
              backgroundColor: cancelReason === option.code ? "var(--color-brand)" : "var(--color-surface)",
              color: cancelReason === option.code ? "var(--color-brand-contrast)" : "var(--color-text)",
            }}
          >
            {option.label}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => setShowCancelForm(false)}
          disabled={isActing}
          className="tap-target rounded-lg border px-4 py-2 text-sm disabled:opacity-60"
          style={{ borderColor: "var(--color-border)" }}
        >
          돌아가기
        </button>
        <button
          type="button"
          onClick={onConfirmCancel}
          disabled={isActing}
          className="tap-target rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-60"
          style={{ backgroundColor: "var(--color-danger)", color: "#ffffff" }}
        >
          {isActing ? "처리 중..." : `${confirmLabel} 확정`}
        </button>
      </div>
    </div>
  );
}
