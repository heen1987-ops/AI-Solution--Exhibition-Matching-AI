"use client";

/**
 * U-14 상담 요청 (`/meetings/new`).
 *
 * 근거 문서
 * ---------
 * - docs/user-ia-wireframes.md 7절 U-14 와이어프레임: 상담 주제 칩, 희망시간 칩, 전달할 내용,
 *   "수락 시 연락처를 공유합니다" 체크박스와 "공유 항목 자세히 보기", "전송 버튼을 누르면
 *   외부 상대에게 요청이 전달되므로 제출 직전에 업체, 시간, 공유정보를 요약한다", "전송 중
 *   버튼을 잠그고 멱등 키로 중복 요청을 막는다".
 * - docs/user-ia-wireframes.md 6.2절(상담 상태모델): `requested` 이후 중복 제출은 동일 멱등
 *   키로 같은 결과를 반환한다.
 * - docs/user-ia-wireframes.md 11.4절: 상담요청처럼 외부 상대에게 전달되는 작업은 네트워크
 *   단절 시 로컬 큐잉 대상이며, 장시간 지연되면 재확인이 필요하다.
 * - docs/frontend-backend-ai-interface-spec.md 12.2~12.3절: 가능시간 조회
 *   `GET /exhibitors/{id}/availability?date=...&topic=...`, 상담 요청
 *   `POST /meetings` 요청 바디(`exhibitor_id`, `topic`, `requested_slot_ids`, `message`,
 *   `contact_share{accepted,document_version,fields}`, `match_result_id`), "연락처 공유
 *   동의는 요청 시 기록하지만 실제 공개는 상담 확정 후".
 * - frontend/lib/types.ts `MeetingCreateRequest`/`ContactShareRequest`/`AvailabilitySlotItem`
 *   그대로 사용.
 *
 * 상담 주제 메모: 6단계(매칭 온톨로지) 문서가 아직 없어 `topic`의 정식 코드 목록은
 * `GET /api/v1/ontology/concepts?concept_type=BUSINESS_GOAL`로 채워야 한다(12.3절 주석,
 * frontend/lib/types.ts MeetingCreateRequest.topic 주석). 그 엔드포인트는 아직 표준 응답
 * 봉투를 쓰지 않아 `frontend/lib/api-client.ts` 범위 밖이므로, 이 화면은 우선 와이어프레임
 * 문구 그대로의 기본 주제 목록을 쓰고, 마운트 시 온톨로지 엔드포인트를 얇게 직접 호출해
 * 성공하면 그 목록으로 교체한다(실패하면 조용히 기본값을 유지 - TODO: 6단계 문서 확정 후
 * 정식 파싱 로직으로 교체).
 *
 * 진입 경로: 부스 상세 등에서 `?exhibitorId=ex_031&exhibitorName=A양조장&matchResultId=mr_001`
 * 쿼리스트링으로 이 화면을 연다(그 화면들은 이 작업 범위 밖이라 실제 링크는 만들지 않았다).
 */

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import {
  ApiClientError,
  generateClientId,
  getExhibitorAvailability,
  postMeetingRequest,
} from "@/lib/api-client";
import { enqueueTask, useIsOnline, useOfflineFlush } from "@/lib/offline-queue";
import type {
  AvailabilitySlotItem,
  ContactShareField,
  MeetingCreateRequest,
} from "@/lib/types";
import { ALLOWED_CONTACT_SHARE_FIELDS } from "@/lib/types";

const QUEUE_KIND = "MEETING_REQUEST";
const CONTACT_SHARE_DOCUMENT_VERSION = "meeting-share-2026.1";

interface TopicOption {
  code: string;
  label: string;
}

// 와이어프레임 U-14 그대로의 기본값. TODO(6단계 온톨로지 문서 확정 후 대조).
const DEFAULT_TOPICS: TopicOption[] = [
  { code: "DISTRIBUTION", label: "입점·유통" },
  { code: "OEM_PB", label: "OEM·PB" },
  { code: "EXPORT", label: "수출" },
  { code: "PRODUCT_PRICE", label: "제품·가격" },
  { code: "TECH_FACILITY", label: "기술·설비" },
];

const CONTACT_FIELD_LABEL: Record<ContactShareField, string> = {
  NAME: "이름",
  PHONE: "휴대전화",
  BUSINESS_EMAIL: "업무용 이메일",
  EMAIL: "이메일",
};

function todayIsoDate(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function formatSlotLabel(slot: AvailabilitySlotItem): string {
  const start = new Date(slot.start_at);
  const end = new Date(slot.end_at);
  const fmt = (d: Date) => d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
  return `${fmt(start)}~${fmt(end)}`;
}

/** 온톨로지 원시 응답의 다양한 가능한 모양을 최선 노력으로 파싱한다. 실패하면 null. */
function tryParseTopicOptions(payload: unknown): TopicOption[] | null {
  const list = Array.isArray(payload)
    ? payload
    : Array.isArray((payload as { items?: unknown[] })?.items)
      ? (payload as { items: unknown[] }).items
      : Array.isArray((payload as { concepts?: unknown[] })?.concepts)
        ? (payload as { concepts: unknown[] }).concepts
        : null;
  if (!list) return null;
  const parsed = list
    .map((row) => {
      const record = row as Record<string, unknown>;
      const code = record.concept_code ?? record.code ?? record.id;
      const label = record.display_name ?? record.label ?? record.name ?? code;
      return typeof code === "string" && typeof label === "string" ? { code, label } : null;
    })
    .filter((v): v is TopicOption => v !== null);
  return parsed.length > 0 ? parsed : null;
}

export default function MeetingRequestPage() {
  return (
    <Suspense fallback={<PageFallback />}>
      <MeetingRequestPageContent />
    </Suspense>
  );
}

function PageFallback() {
  return (
    <div className="mx-auto max-w-screen-content px-4 py-6">
      <p style={{ color: "var(--color-text-muted)" }}>불러오는 중...</p>
    </div>
  );
}

function MeetingRequestPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const isOnline = useIsOnline();

  const exhibitorId = searchParams?.get("exhibitorId") ?? "";
  const exhibitorName = searchParams?.get("exhibitorName") ?? "업체";
  const matchResultId = searchParams?.get("matchResultId");

  const [topics, setTopics] = useState<TopicOption[]>(DEFAULT_TOPICS);
  const [topic, setTopic] = useState<string>("");
  const [date] = useState(todayIsoDate());
  const [slots, setSlots] = useState<AvailabilitySlotItem[]>([]);
  const [loadingSlots, setLoadingSlots] = useState(false);
  const [slotsError, setSlotsError] = useState<string | null>(null);
  const [selectedSlotIds, setSelectedSlotIds] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [shareContact, setShareContact] = useState(false);
  const [showShareDetail, setShowShareDetail] = useState(false);
  const [shareFields, setShareFields] = useState<ContactShareField[]>(["NAME", "PHONE"]);

  const [step, setStep] = useState<"FORM" | "REVIEW">("FORM");
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null);
  const [submitState, setSubmitState] = useState<"idle" | "submitting" | "queued" | "error">(
    "idle",
  );
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  // 온톨로지 주제 목록을 얇게 직접 호출로 시도한다 (api-client.ts 범위 밖, 실패해도 기본값 유지).
  useEffect(() => {
    let cancelled = false;
    fetch("/api/v1/ontology/concepts?concept_type=BUSINESS_GOAL", { credentials: "include" })
      .then((res) => (res.ok ? res.json() : null))
      .then((payload) => {
        if (cancelled || !payload) return;
        const parsed = tryParseTopicOptions(payload);
        if (parsed) setTopics(parsed);
      })
      .catch(() => {
        // 온톨로지 조회 실패 시 기본 주제 목록을 그대로 쓴다.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!topic || !exhibitorId) return;
    let cancelled = false;
    setLoadingSlots(true);
    setSlotsError(null);
    getExhibitorAvailability(exhibitorId, { date, topic })
      .then((res) => {
        if (!cancelled) setSlots(res.items);
      })
      .catch((err) => {
        if (cancelled) return;
        setSlotsError(err instanceof ApiClientError ? err.message : "가능한 시간을 불러오지 못했습니다.");
      })
      .finally(() => {
        if (!cancelled) setLoadingSlots(false);
      });
    return () => {
      cancelled = true;
    };
  }, [topic, exhibitorId, date]);

  function toggleSlot(slotId: string) {
    setSelectedSlotIds((prev) =>
      prev.includes(slotId) ? prev.filter((id) => id !== slotId) : [...prev, slotId],
    );
  }

  function toggleShareField(field: ContactShareField) {
    setShareFields((prev) =>
      prev.includes(field) ? prev.filter((f) => f !== field) : [...prev, field],
    );
  }

  const selectedSlotLabels = useMemo(
    () =>
      selectedSlotIds
        .map((id) => slots.find((s) => s.slot_id === id))
        .filter((s): s is AvailabilitySlotItem => Boolean(s))
        .map(formatSlotLabel),
    [selectedSlotIds, slots],
  );

  function buildRequest(): MeetingCreateRequest {
    return {
      exhibitor_id: exhibitorId,
      topic,
      requested_slot_ids: selectedSlotIds,
      message: message.trim() || null,
      contact_share: {
        accepted: shareContact,
        document_version: shareContact ? CONTACT_SHARE_DOCUMENT_VERSION : null,
        fields: shareContact ? shareFields : [],
      },
      match_result_id: matchResultId ?? null,
    };
  }

  function goToReview() {
    setFormError(null);
    if (!exhibitorId) {
      setFormError("업체 정보를 확인할 수 없습니다. 부스 상세 화면에서 다시 시도해 주세요.");
      return;
    }
    if (!topic) {
      setFormError("상담 주제를 선택해 주세요.");
      return;
    }
    if (selectedSlotIds.length === 0) {
      setFormError("희망 시간을 1개 이상 선택해 주세요.");
      return;
    }
    // 리뷰 단계로 넘어갈 때 멱등키를 한 번만 만들고, 재시도(오프라인 큐 포함)에서는 계속
    // 재사용한다 (4.2절: 같은 키·같은 본문은 최초 결과를 재사용한다).
    setIdempotencyKey(generateClientId());
    setStep("REVIEW");
  }

  // 6.4절 상태모델: 오프라인 큐에 남은 상담 요청을 온라인 복귀 시 같은 멱등키로 재전송한다.
  useOfflineFlush<MeetingCreateRequest>(QUEUE_KIND, async (payload, key) => {
    const result = await postMeetingRequest(payload, { idempotencyKey: key });
    router.replace(`/meetings/${result.meeting_id}`);
    return { resultId: result.meeting_id };
  });

  async function handleConfirmSend() {
    if (submitState === "submitting" || submitState === "queued") return; // 버튼 잠금.
    const request = buildRequest();
    const key = idempotencyKey ?? generateClientId();
    setSubmitState("submitting");
    setSubmitError(null);
    try {
      const result = await postMeetingRequest(request, { idempotencyKey: key });
      router.push(`/meetings/${result.meeting_id}`);
    } catch (err) {
      if (err instanceof ApiClientError && (err.code === "NETWORK_ERROR" || err.retryable)) {
        enqueueTask(QUEUE_KIND, request, key);
        setSubmitState("queued");
      } else if (err instanceof ApiClientError) {
        setSubmitState("error");
        setSubmitError(err.message);
      } else {
        setSubmitState("error");
        setSubmitError("상담 요청을 보내지 못했습니다.");
      }
    }
  }

  if (submitState === "queued") {
    return (
      <div className="mx-auto flex max-w-screen-content flex-col gap-4 px-4 py-6">
        <h1 className="text-xl font-bold">상담 요청을 저장했습니다</h1>
        <p style={{ color: "var(--color-text-muted)" }}>
          지금은 네트워크에 연결할 수 없어 요청을 임시 저장했습니다. 연결이 되면 자동으로
          {exhibitorName}에 전송하고, 완료되면 상담 상세 화면으로 이동합니다.
        </p>
        {!isOnline ? (
          <p role="status" aria-live="polite" className="text-sm" style={{ color: "var(--color-brand)" }}>
            현재 오프라인 상태입니다.
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-screen-content flex-col gap-6 px-4 py-6">
      <header>
        <h1 className="text-xl font-bold">{exhibitorName} 상담 요청</h1>
      </header>

      {step === "FORM" ? (
        <>
          <section aria-labelledby="topic-heading" className="flex flex-col gap-2">
            <h2 id="topic-heading" className="text-base font-semibold">
              상담 주제
            </h2>
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="상담 주제 선택">
              {topics.map((option) => (
                <button
                  key={option.code}
                  type="button"
                  role="radio"
                  aria-checked={topic === option.code}
                  onClick={() => setTopic(option.code)}
                  className="tap-target rounded-full border px-4 py-2 text-sm"
                  style={{
                    borderColor: topic === option.code ? "var(--color-brand)" : "var(--color-border)",
                    backgroundColor: topic === option.code ? "var(--color-brand)" : "var(--color-surface)",
                    color: topic === option.code ? "var(--color-brand-contrast)" : "var(--color-text)",
                    fontWeight: topic === option.code ? 700 : 500,
                  }}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </section>

          <section aria-labelledby="slots-heading" className="flex flex-col gap-2">
            <h2 id="slots-heading" className="text-base font-semibold">
              희망시간
            </h2>
            {!topic ? (
              <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
                먼저 상담 주제를 선택해 주세요.
              </p>
            ) : loadingSlots ? (
              <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
                가능한 시간을 불러오는 중...
              </p>
            ) : slotsError ? (
              <p role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
                {slotsError}
              </p>
            ) : slots.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
                오늘은 가능한 시간이 없습니다.
              </p>
            ) : (
              <div className="flex flex-wrap gap-2" role="group" aria-label="희망 시간 선택(복수 선택)">
                {slots.map((slot) => {
                  const full = slot.reserved_count >= slot.capacity;
                  const selected = selectedSlotIds.includes(slot.slot_id);
                  return (
                    <button
                      key={slot.slot_id}
                      type="button"
                      onClick={() => !full && toggleSlot(slot.slot_id)}
                      disabled={full}
                      aria-pressed={selected}
                      className="tap-target rounded-full border px-4 py-2 text-sm disabled:opacity-40"
                      style={{
                        borderColor: selected ? "var(--color-brand)" : "var(--color-border)",
                        backgroundColor: selected ? "var(--color-brand)" : "var(--color-surface)",
                        color: selected ? "var(--color-brand-contrast)" : "var(--color-text)",
                        fontWeight: selected ? 700 : 500,
                      }}
                    >
                      {formatSlotLabel(slot)}
                      {full ? " · 마감" : ""}
                    </button>
                  );
                })}
              </div>
            )}
          </section>

          <section aria-labelledby="message-heading" className="flex flex-col gap-2">
            <h2 id="message-heading" className="text-base font-semibold">
              전달할 내용
            </h2>
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              maxLength={500}
              rows={4}
              placeholder="상담에서 다루고 싶은 내용을 적어 주세요. (선택)"
              className="rounded-lg border px-3 py-2 text-base"
              style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
            />
          </section>

          <section aria-labelledby="share-heading" className="flex flex-col gap-2">
            <h2 id="share-heading" className="sr-only">
              연락처 공유
            </h2>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={shareContact}
                onChange={(event) => setShareContact(event.target.checked)}
                className="tap-target"
              />
              수락 시 연락처를 공유합니다
            </label>
            <button
              type="button"
              onClick={() => setShowShareDetail((v) => !v)}
              className="self-start text-sm underline"
              style={{ color: "var(--color-brand)" }}
              aria-expanded={showShareDetail}
            >
              공유 항목 자세히 보기
            </button>
            {showShareDetail ? (
              <div className="flex flex-col gap-1 rounded-lg border p-3" style={{ borderColor: "var(--color-border)" }}>
                <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
                  업체가 상담을 수락한 뒤에만 아래에서 선택한 항목이 공개됩니다.
                </p>
                {ALLOWED_CONTACT_SHARE_FIELDS.map((field) => (
                  <label key={field} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      disabled={!shareContact}
                      checked={shareFields.includes(field)}
                      onChange={() => toggleShareField(field)}
                      className="tap-target"
                    />
                    {CONTACT_FIELD_LABEL[field]}
                  </label>
                ))}
              </div>
            ) : null}
          </section>

          {formError ? (
            <p role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
              {formError}
            </p>
          ) : null}

          <button
            type="button"
            onClick={goToReview}
            className="tap-target rounded-lg px-5 py-3 text-sm font-semibold"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
          >
            상담 요청 보내기
          </button>
        </>
      ) : (
        <section aria-labelledby="review-heading" className="flex flex-col gap-4">
          <h2 id="review-heading" className="text-base font-semibold">
            요청 전 확인
          </h2>
          <dl
            className="flex flex-col gap-2 rounded-lg border p-4 text-sm"
            style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
          >
            <div className="flex justify-between gap-4">
              <dt style={{ color: "var(--color-text-muted)" }}>업체</dt>
              <dd className="text-right font-medium">{exhibitorName}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt style={{ color: "var(--color-text-muted)" }}>주제</dt>
              <dd className="text-right font-medium">
                {topics.find((t) => t.code === topic)?.label ?? topic}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt style={{ color: "var(--color-text-muted)" }}>희망시간</dt>
              <dd className="text-right font-medium">{selectedSlotLabels.join(", ")}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt style={{ color: "var(--color-text-muted)" }}>연락처 공유</dt>
              <dd className="text-right font-medium">
                {shareContact
                  ? `수락 시 공개(${shareFields.map((f) => CONTACT_FIELD_LABEL[f]).join(", ") || "없음"})`
                  : "공유하지 않음"}
              </dd>
            </div>
            {message.trim() ? (
              <div className="flex flex-col gap-1">
                <dt style={{ color: "var(--color-text-muted)" }}>전달할 내용</dt>
                <dd>{message.trim()}</dd>
              </div>
            ) : null}
          </dl>
          <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
            보내면 {exhibitorName}에 상담 요청이 전달됩니다. 이후 상담 상세 화면에서 상태를 확인할
            수 있습니다.
          </p>

          {submitError ? (
            <p role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
              {submitError}
            </p>
          ) : null}

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => setStep("FORM")}
              disabled={submitState === "submitting"}
              className="tap-target rounded-lg border px-5 py-3 text-sm font-semibold disabled:opacity-60"
              style={{ borderColor: "var(--color-border)" }}
            >
              내용 수정
            </button>
            <button
              type="button"
              onClick={handleConfirmSend}
              disabled={submitState === "submitting"}
              className="tap-target rounded-lg px-5 py-3 text-sm font-semibold disabled:opacity-60"
              style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
            >
              {submitState === "submitting" ? "보내는 중..." : "네, 보내기"}
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
