"use client";

/**
 * U-16 QR 체크인 (`/check-in/{qrToken}`).
 *
 * 근거 문서
 * ---------
 * - docs/user-ia-wireframes.md 7절 U-16: "무엇을 하셨나요?" 선택지(시음/구매/상담/정보 확인/
 *   대기 후 이탈), "[저장하고 다음 추천]". "QR 토큰은 부스·행사·만료시간을 서명하며 사용자
 *   ID를 포함하지 않는다.", "같은 사용자의 짧은 시간 내 중복 스캔은 하나의 방문으로 묶는다.",
 *   "카메라 권한을 거부해도 QR 링크 직접 접속 또는 코드 입력으로 체크인할 수 있다."
 * - docs/user-ia-wireframes.md 13.2절: "카메라 없이 QR 체크인 가능한 대체수단 제공" - 이
 *   화면은 카메라를 아예 쓰지 않고 URL 경로 자체(QR 링크) 또는 수동 코드 입력만으로 동작한다.
 * - docs/user-ia-wireframes.md 6.4절, 11.4절: 체크인은 오프라인 로컬 큐 대상이며 멱등키로
 *   중복 제출을 막는다.
 * - docs/frontend-backend-ai-interface-spec.md 13.1절: `POST /check-ins` 요청 바디, "중복이면
 *   오류만 반환하지 않고 기존 체크인 ID와 시각을 제공한다".
 * - frontend/lib/api-client.ts `postCheckIn` 그대로 사용(멱등키 자동 생성 로직이 있지만, 이
 *   화면은 오프라인 재전송 시 같은 키를 재사용해야 하므로 직접 키를 만들어 넘긴다).
 *
 * 흐름 메모: 체크인 성공 후에는 이 작업 범위에 함께 포함된 U-17 피드백 화면
 * (`/visits/{visitId}/feedback`)으로 이동해 "체크인 → 피드백 → 다음 추천"의 종단 시나리오
 * (16절 우선 제작 순서 예시 퍼널)를 완성한다. 서버가 부여한 `check_in_id`를 `visitId`로 쓴다.
 */

import { Suspense, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { ApiClientError, generateClientId, postCheckIn } from "@/lib/api-client";
import { enqueueTask, useIsOnline, useOfflineFlush } from "@/lib/offline-queue";
import type { CheckInActivity, CheckInRequest } from "@/lib/types";

const QUEUE_KIND = "CHECK_IN";

const ACTIVITY_OPTIONS: { code: CheckInActivity; label: string }[] = [
  { code: "TASTING", label: "시음" },
  { code: "PURCHASE", label: "구매" },
  { code: "MEETING", label: "상담" },
  { code: "INFO_CHECK", label: "정보 확인" },
  { code: "LEFT_WAITING", label: "대기 후 이탈" },
];

export default function CheckInPage() {
  return (
    <Suspense fallback={<PageFallback />}>
      <CheckInPageContent />
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

function CheckInPageContent() {
  const params = useParams<{ qrToken: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const isOnline = useIsOnline();

  const qrToken = params?.qrToken ?? "";
  const boothName = searchParams?.get("boothName") ?? "부스";
  const matchResultId = searchParams?.get("matchResultId");
  const fallbackBoothId = searchParams?.get("boothId");

  if (qrToken === "enter") {
    return <ManualCodeEntry />;
  }

  return (
    <CheckInForm
      qrToken={qrToken}
      boothName={boothName}
      matchResultId={matchResultId}
      fallbackBoothId={fallbackBoothId}
      isOnline={isOnline}
      onSuccess={(checkInId, boothId, duplicate) => {
        const objectId = boothId ?? fallbackBoothId ?? "";
        const query = new URLSearchParams({ objectType: "BOOTH", objectId });
        if (matchResultId) query.set("matchResultId", matchResultId);
        // 13.1절: 중복 스캔은 오류가 아니라 기존 체크인으로 안내한다.
        if (duplicate) query.set("duplicate", "1");
        router.push(`/visits/${encodeURIComponent(checkInId)}/feedback?${query.toString()}`);
      }}
    />
  );
}

function ManualCodeEntry() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit() {
    const trimmed = code.trim();
    if (!trimmed) {
      setError("코드를 입력해 주세요.");
      return;
    }
    router.push(`/check-in/${encodeURIComponent(trimmed)}`);
  }

  return (
    <div className="mx-auto flex max-w-screen-content flex-col gap-4 px-4 py-6">
      <h1 className="text-xl font-bold">체크인 코드 입력</h1>
      <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
        카메라를 쓸 수 없다면 부스에 표시된 체크인 코드를 직접 입력해 주세요.
      </p>
      <label className="flex flex-col gap-1 text-sm">
        <span>체크인 코드</span>
        <input
          type="text"
          value={code}
          onChange={(event) => setCode(event.target.value)}
          className="rounded-lg border px-3 py-2 text-base"
          style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
          aria-describedby={error ? "code-error" : undefined}
        />
      </label>
      {error ? (
        <p id="code-error" role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
          {error}
        </p>
      ) : null}
      <button
        type="button"
        onClick={submit}
        className="tap-target w-fit rounded-lg px-5 py-3 text-sm font-semibold"
        style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
      >
        확인
      </button>
    </div>
  );
}

function CheckInForm({
  qrToken,
  boothName,
  matchResultId,
  fallbackBoothId,
  isOnline,
  onSuccess,
}: {
  qrToken: string;
  boothName: string;
  matchResultId: string | null;
  fallbackBoothId: string | null;
  isOnline: boolean;
  onSuccess: (checkInId: string, boothId: string | null, duplicate: boolean) => void;
}) {
  const router = useRouter();
  const [activities, setActivities] = useState<CheckInActivity[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queuedMessage, setQueuedMessage] = useState<string | null>(null);

  const queueKind = `${QUEUE_KIND}:${qrToken}`;

  // 6.4절 상태모델: 오프라인 큐에 남은 체크인을 온라인 복귀 시 같은 멱등키로 재전송한다.
  useOfflineFlush<CheckInRequest>(queueKind, async (payload, key) => {
    const result = await postCheckIn(payload, { idempotencyKey: key });
    return { resultId: result.check_in_id };
  });

  function toggleActivity(code: CheckInActivity) {
    setActivities((prev) => (prev.includes(code) ? prev.filter((a) => a !== code) : [...prev, code]));
  }

  async function handleSubmit() {
    if (isSubmitting) return; // 멱등 제출: 중복 클릭 방지를 위한 버튼 잠금.
    if (activities.length === 0) {
      setError("무엇을 하셨는지 하나 이상 선택해 주세요.");
      return;
    }
    setError(null);
    setIsSubmitting(true);

    const clientEventId = generateClientId();
    const request: CheckInRequest = {
      qr_token: qrToken,
      activities,
      match_result_id: matchResultId ?? null,
      client_event_id: clientEventId,
      occurred_at: new Date().toISOString(),
    };

    try {
      const result = await postCheckIn(request, { idempotencyKey: clientEventId });
      onSuccess(result.check_in_id, result.booth_id, result.duplicate);
    } catch (err) {
      if (err instanceof ApiClientError && (err.code === "NETWORK_ERROR" || err.retryable)) {
        enqueueTask(queueKind, request, clientEventId);
        if (fallbackBoothId) {
          setQueuedMessage(
            "오프라인 상태라 체크인을 저장했습니다. 연결되면 자동으로 전송됩니다. 지금 바로 짧은 피드백을 남길 수도 있어요.",
          );
        } else {
          setQueuedMessage(
            "오프라인 상태라 체크인을 저장했습니다. 연결되면 자동으로 전송됩니다.",
          );
        }
      } else if (err instanceof ApiClientError && err.code === "INVALID_QR") {
        setError("QR 코드가 만료되었거나 유효하지 않습니다. 부스 담당자에게 문의해 주세요.");
      } else if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("체크인을 저장하지 못했습니다.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  if (queuedMessage) {
    return (
      <div className="mx-auto flex max-w-screen-content flex-col gap-4 px-4 py-6">
        <h1 className="text-xl font-bold">{boothName} 방문 확인</h1>
        <p role="status" aria-live="polite">
          {queuedMessage}
        </p>
        {fallbackBoothId ? (
          <button
            type="button"
            onClick={() => {
              const query = new URLSearchParams({ objectType: "BOOTH", objectId: fallbackBoothId });
              if (matchResultId) query.set("matchResultId", matchResultId);
              router.push(`/visits/local-${Date.now()}/feedback?${query.toString()}`);
            }}
            className="tap-target w-fit rounded-lg px-5 py-3 text-sm font-semibold"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
          >
            지금 피드백 남기기
          </button>
        ) : (
          <button
            type="button"
            onClick={() => router.push("/home")}
            className="tap-target w-fit rounded-lg px-5 py-3 text-sm font-semibold"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
          >
            홈으로
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-screen-content flex-col gap-6 px-4 py-6">
      <header>
        <h1 className="text-xl font-bold">{boothName} 방문 확인</h1>
      </header>

      {!isOnline ? (
        <p role="status" aria-live="polite" className="text-sm" style={{ color: "var(--color-brand)" }}>
          오프라인 상태입니다. 저장하면 연결되는 즉시 자동으로 전송됩니다.
        </p>
      ) : null}

      <section aria-labelledby="activity-heading" className="flex flex-col gap-3">
        <h2 id="activity-heading" className="text-base font-semibold">
          무엇을 하셨나요?
        </h2>
        <div className="flex flex-wrap gap-2" role="group" aria-label="활동 선택(복수 선택)">
          {ACTIVITY_OPTIONS.map((option) => {
            const selected = activities.includes(option.code);
            return (
              <button
                key={option.code}
                type="button"
                onClick={() => toggleActivity(option.code)}
                aria-pressed={selected}
                className="tap-target rounded-full border px-4 py-2 text-sm"
                style={{
                  borderColor: selected ? "var(--color-brand)" : "var(--color-border)",
                  backgroundColor: selected ? "var(--color-brand)" : "var(--color-surface)",
                  color: selected ? "var(--color-brand-contrast)" : "var(--color-text)",
                  fontWeight: selected ? 700 : 500,
                }}
              >
                {option.label}
              </button>
            );
          })}
        </div>
      </section>

      {error ? (
        <p role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
          {error}
        </p>
      ) : null}

      <button
        type="button"
        onClick={handleSubmit}
        disabled={isSubmitting}
        className="tap-target w-fit rounded-lg px-5 py-3 text-sm font-semibold disabled:opacity-60"
        style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
      >
        {isSubmitting ? "저장 중..." : "저장하고 다음 추천"}
      </button>

      <a href="/check-in/enter" className="w-fit text-sm underline" style={{ color: "var(--color-brand)" }}>
        카메라 대신 코드 직접 입력
      </a>
    </div>
  );
}
