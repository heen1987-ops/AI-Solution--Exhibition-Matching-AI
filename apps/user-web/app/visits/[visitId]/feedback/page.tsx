"use client";

/**
 * U-17 방문 피드백 (`/visits/{visitId}/feedback`).
 *
 * 근거 문서
 * ---------
 * - docs/user-ia-wireframes.md 7절 U-17: "한 번의 적합도 선택과 선택형 이유로 5초 안에
 *   끝낸다.", "서술형 입력은 선택사항이다.", "피드백 저장 직후 다음 추천을 보여준다.",
 *   "`부적합`은 사용자가 원하면 해당 업체·제품을 이후 추천에서 제외한다."
 * - docs/user-ia-wireframes.md 12.1절 이벤트 이름 규칙의 `feedback_submitted`,
 *   `recommendation_dismissed`(부적합 + 제외 선택 시 함께 기록).
 * - docs/user-ia-wireframes.md 6.4절, 11.4절: 피드백도 오프라인 로컬 큐 대상이다.
 * - docs/frontend-backend-ai-interface-spec.md 13.2절: `POST /feedback` 요청 바디
 *   (`object_type`,`object_id`,`match_result_id`,`rating`,`positive_reasons`,
 *   `negative_reasons`,`comment`,`client_event_id`), 원인별 처리표(맛/가격/혼잡/품절/설명오류).
 * - frontend/lib/types.ts `FeedbackRequest`/`FeedbackRating`/`FeedbackReasonCode` 그대로 사용.
 *
 * 라우트 계약 메모: 인터페이스 명세·db-erd에는 `visit_id`를 받는 피드백 스키마가 없고
 * (frontend/lib/types.ts 13절 주석: "예시 요청 JSON은 있으나 응답 JSON은 프로즈 설명뿐"),
 * `FeedbackRequest`는 `object_type`/`object_id`로 식별한다. 이 화면은 URL의 `visitId`를
 * 표시·추적용 참조로만 쓰고, 실제 API 호출에는 쿼리스트링으로 전달된 `objectType`/`objectId`/
 * `matchResultId`를 쓴다(U-16 체크인 화면이 성공 후 이 형태로 링크한다).
 */

import { Suspense, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { ApiClientError, generateClientId, postFeedback, postInteraction } from "@/lib/api-client";
import { enqueueTask, useIsOnline, useOfflineFlush } from "@/lib/offline-queue";
import type {
  FeedbackRating,
  FeedbackReasonCode,
  FeedbackRequest,
  RecommendableObjectType,
} from "@/lib/types";

const QUEUE_KIND = "FEEDBACK";

const RATING_OPTIONS: { code: FeedbackRating; label: string }[] = [
  { code: "VERY_RELEVANT", label: "잘 맞아요" },
  { code: "RELEVANT", label: "괜찮아요" },
  { code: "NOT_RELEVANT", label: "안 맞아요" },
];

const REASON_LABEL: Record<FeedbackReasonCode, string> = {
  TASTE: "맛·제품",
  PRICE: "가격",
  CONGESTION: "혼잡·대기",
  SOLD_OUT_OR_CLOSED: "품절·운영종료",
  EXPLANATION_ERROR: "추천 설명이 실제와 달라요",
};

const REASON_OPTIONS: FeedbackReasonCode[] = [
  "TASTE",
  "PRICE",
  "CONGESTION",
  "SOLD_OUT_OR_CLOSED",
  "EXPLANATION_ERROR",
];

export default function VisitFeedbackPage() {
  return (
    <Suspense fallback={<PageFallback />}>
      <VisitFeedbackPageContent />
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

function VisitFeedbackPageContent() {
  const params = useParams<{ visitId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const isOnline = useIsOnline();

  const visitId = params?.visitId ?? "";
  const objectType = (searchParams?.get("objectType") ?? "BOOTH") as RecommendableObjectType;
  const objectId = searchParams?.get("objectId") ?? "";
  const matchResultId = searchParams?.get("matchResultId");
  // 13.1절: 중복 QR 스캔은 오류가 아니라 기존 체크인 하나로 묶인다 - 체크인 화면이 안내용으로 넘긴다.
  const wasDuplicateCheckIn = searchParams?.get("duplicate") === "1";

  const [rating, setRating] = useState<FeedbackRating | null>(null);
  const [reasons, setReasons] = useState<FeedbackReasonCode[]>([]);
  const [comment, setComment] = useState("");
  const [excludeFromFuture, setExcludeFromFuture] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queuedMessage, setQueuedMessage] = useState<string | null>(null);

  const queueKind = `${QUEUE_KIND}:${visitId}`;

  // 6.4절 상태모델: 오프라인 큐에 남은 피드백을 온라인 복귀 시 같은 멱등키로 재전송한다.
  useOfflineFlush<FeedbackRequest>(queueKind, async (payload, key) => {
    const result = await postFeedback(payload, { idempotencyKey: key });
    return { resultId: result.feedback_id };
  });

  function toggleReason(code: FeedbackReasonCode) {
    setReasons((prev) => (prev.includes(code) ? prev.filter((r) => r !== code) : [...prev, code]));
  }

  if (!objectId) {
    return (
      <div className="mx-auto flex max-w-screen-content flex-col gap-4 px-4 py-6">
        <h1 className="text-xl font-bold">피드백</h1>
        <p style={{ color: "var(--color-text-muted)" }}>
          무엇에 대한 방문인지 확인할 수 없어 피드백을 남길 수 없습니다.
        </p>
        <button
          type="button"
          onClick={() => router.push("/home")}
          className="tap-target w-fit rounded-lg px-5 py-3 text-sm font-semibold"
          style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
        >
          홈으로
        </button>
      </div>
    );
  }

  async function handleSubmit() {
    if (isSubmitting) return; // 멱등 제출: 중복 클릭 방지를 위한 버튼 잠금.
    if (!rating) {
      setError("적합도를 선택해 주세요.");
      return;
    }
    setError(null);
    setIsSubmitting(true);

    const clientEventId = generateClientId();
    const request: FeedbackRequest = {
      object_type: objectType,
      object_id: objectId,
      match_result_id: matchResultId ?? null,
      rating,
      positive_reasons: rating === "NOT_RELEVANT" ? [] : reasons,
      negative_reasons: rating === "NOT_RELEVANT" ? reasons : [],
      comment: comment.trim() || null,
      client_event_id: clientEventId,
    };

    try {
      await postFeedback(request, { idempotencyKey: clientEventId });
      await maybeDismiss();
      router.push("/home");
    } catch (err) {
      if (err instanceof ApiClientError && (err.code === "NETWORK_ERROR" || err.retryable)) {
        enqueueTask(queueKind, request, clientEventId);
        setQueuedMessage(
          "오프라인 상태라 피드백을 저장했습니다. 연결되면 자동으로 전송되고, 다음 추천은 지금 바로 볼 수 있어요.",
        );
      } else if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("피드백을 저장하지 못했습니다.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  async function maybeDismiss() {
    if (rating !== "NOT_RELEVANT" || !excludeFromFuture) return;
    try {
      // 12.1절 이벤트 이름 규칙: recommendation_dismissed. 실패해도 피드백 자체 제출은
      // 이미 끝났으므로 화면 흐름을 막지 않는다.
      await postInteraction({
        event_type: "RECOMMENDATION_DISMISSED",
        object_type: objectType,
        object_id: objectId,
        match_result_id: matchResultId ?? null,
        occurred_at: new Date().toISOString(),
      });
    } catch {
      // 무시 - 부가 신호일 뿐이다.
    }
  }

  if (queuedMessage) {
    return (
      <div className="mx-auto flex max-w-screen-content flex-col gap-4 px-4 py-6">
        <h1 className="text-xl font-bold">피드백</h1>
        <p role="status" aria-live="polite">
          {queuedMessage}
        </p>
        <button
          type="button"
          onClick={() => router.push("/home")}
          className="tap-target w-fit rounded-lg px-5 py-3 text-sm font-semibold"
          style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
        >
          다음 추천 보기
        </button>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-screen-content flex-col gap-6 px-4 py-6">
      <header>
        <h1 className="text-xl font-bold">방문은 어떠셨나요?</h1>
      </header>

      {wasDuplicateCheckIn ? (
        <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
          이미 방금 전 같은 곳에 체크인한 기록이 있어 하나의 방문으로 합쳐 두었습니다.
        </p>
      ) : null}

      {!isOnline ? (
        <p role="status" aria-live="polite" className="text-sm" style={{ color: "var(--color-brand)" }}>
          오프라인 상태입니다. 제출하면 연결되는 즉시 자동으로 전송됩니다.
        </p>
      ) : null}

      <section aria-labelledby="rating-heading" className="flex flex-col gap-3">
        <h2 id="rating-heading" className="text-base font-semibold">
          이 추천, 적합했나요?
        </h2>
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="적합도 선택">
          {RATING_OPTIONS.map((option) => (
            <button
              key={option.code}
              type="button"
              role="radio"
              aria-checked={rating === option.code}
              onClick={() => {
                setRating(option.code);
                setReasons([]);
              }}
              className="tap-target rounded-full border px-4 py-2 text-sm"
              style={{
                borderColor: rating === option.code ? "var(--color-brand)" : "var(--color-border)",
                backgroundColor: rating === option.code ? "var(--color-brand)" : "var(--color-surface)",
                color: rating === option.code ? "var(--color-brand-contrast)" : "var(--color-text)",
                fontWeight: rating === option.code ? 700 : 500,
              }}
            >
              {option.label}
            </button>
          ))}
        </div>
      </section>

      {rating ? (
        <section aria-labelledby="reason-heading" className="flex flex-col gap-3">
          <h2 id="reason-heading" className="text-base font-semibold">
            {rating === "NOT_RELEVANT" ? "어떤 점이 아쉬웠나요? (선택)" : "어떤 점이 좋았나요? (선택)"}
          </h2>
          <div className="flex flex-wrap gap-2" role="group" aria-label="이유 선택(복수 선택)">
            {REASON_OPTIONS.map((code) => {
              const selected = reasons.includes(code);
              return (
                <button
                  key={code}
                  type="button"
                  onClick={() => toggleReason(code)}
                  aria-pressed={selected}
                  className="tap-target rounded-full border px-3 py-2 text-sm"
                  style={{
                    borderColor: selected ? "var(--color-brand)" : "var(--color-border)",
                    backgroundColor: selected ? "var(--color-brand)" : "var(--color-surface)",
                    color: selected ? "var(--color-brand-contrast)" : "var(--color-text)",
                  }}
                >
                  {REASON_LABEL[code]}
                </button>
              );
            })}
          </div>
        </section>
      ) : null}

      {rating === "NOT_RELEVANT" ? (
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={excludeFromFuture}
            onChange={(event) => setExcludeFromFuture(event.target.checked)}
            className="tap-target"
          />
          이후 추천에서 이 업체·제품을 제외해 주세요
        </label>
      ) : null}

      <label className="flex flex-col gap-1 text-sm">
        <span>더 하고 싶은 말 (선택)</span>
        <textarea
          value={comment}
          onChange={(event) => setComment(event.target.value)}
          maxLength={300}
          rows={3}
          className="rounded-lg border px-3 py-2 text-base"
          style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
        />
      </label>

      {error ? (
        <p role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
          {error}
        </p>
      ) : null}

      <button
        type="button"
        onClick={handleSubmit}
        disabled={isSubmitting || !rating}
        className="tap-target w-fit rounded-lg px-5 py-3 text-sm font-semibold disabled:opacity-60"
        style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
      >
        {isSubmitting ? "저장 중..." : "제출하고 다음 추천 보기"}
      </button>
    </div>
  );
}
