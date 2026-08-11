"use client";

/**
 * 이벤트 메시지 상세 - 편집(초안/미리보기완료/승인 상태만) + 미리보기 계산 + 워크플로 액션
 * (승인/예약/발행/취소/종료). 각 액션 버튼은 `features/event-message/logic.ts::canTransition`
 * 이 허용하는 현재 상태에서만 노출된다 - 서버도 동일 규칙을 다시 검사하므로(row_version
 * 낙관적 잠금 포함) 이 화면의 버튼 숨김은 UX 편의일 뿐 유일한 방어선이 아니다.
 */

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import RoleGate from "@/components/RoleGate";

import {
  approveEventMessage,
  cancelEventMessage,
  completeEventMessage,
  getEventMessage,
  previewEventMessage,
  publishEventMessage,
  scheduleEventMessage,
  updateEventMessage,
} from "@/features/event-message/api";
import EventMessageForm, {
  type EventMessageFormValue,
} from "@/features/event-message/components/EventMessageForm";
import EventMessagePreviewPanel from "@/features/event-message/components/EventMessagePreviewPanel";
import WorkflowStatusBadge from "@/features/event-message/components/WorkflowStatusBadge";
import { canTransition, isEditable } from "@/features/event-message/logic";
import type { EventMessage, EventMessagePreview } from "@/features/event-message/types";

export default function EventMessageDetailPage() {
  return (
    <RoleGate capability="EVENT_MANAGE" fallback={<NoAccessNotice />}>
      <DetailBody />
    </RoleGate>
  );
}

function NoAccessNotice() {
  return (
    <p className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm text-[var(--color-text-muted)]">
      현재 역할에는 이벤트 메시지 작성 권한이 없습니다.
    </p>
  );
}

function DetailBody() {
  const params = useParams<{ eventMessageId: string }>();
  const router = useRouter();
  const eventMessageId = params.eventMessageId;

  const [message, setMessage] = useState<EventMessage | null>(null);
  const [preview, setPreview] = useState<EventMessagePreview | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setError(null);
    getEventMessage(eventMessageId)
      .then(setMessage)
      .catch((err) => setError(err));
  }, [eventMessageId]);

  useEffect(() => {
    load();
  }, [load]);

  const runAction = async (action: () => Promise<EventMessage | { event_message: EventMessage }>) => {
    setBusy(true);
    setError(null);
    try {
      const result = await action();
      const updated = "event_message" in result ? result.event_message : result;
      setMessage(updated);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const runPreview = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await previewEventMessage(eventMessageId);
      setPreview(result);
      load(); // 상태(DRAFT -> PREVIEWED)와 row_version 갱신 반영
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const submitEdit = async (value: EventMessageFormValue) => {
    if (!message) return;
    await runAction(() =>
      updateEventMessage(eventMessageId, {
        row_version: message.row_version,
        message_type: value.message_type,
        title: value.title,
        body: value.body,
        channels: value.channels,
        target_segment: value.target_segment,
        target_role_code: value.target_role_code,
        destination_screen: value.destination_screen,
        scheduled_at: value.scheduled_at ? new Date(value.scheduled_at).toISOString() : null,
      }),
    );
  };

  if (error != null && message == null) return <ErrorBanner error={error} onRetry={load} />;
  if (!message) return <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>;

  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">{message.title}</h1>
        <WorkflowStatusBadge status={message.status} />
      </div>

      {error != null && <ErrorBanner error={error} />}

      <div className="flex flex-wrap gap-2">
        <ActionButton
          label="미리보기 계산"
          visible={canTransition(message.status, "PREVIEWED") || message.status === "PREVIEWED"}
          busy={busy}
          onClick={runPreview}
        />
        <ActionButton
          label="승인"
          visible={canTransition(message.status, "APPROVED")}
          busy={busy}
          onClick={() =>
            runAction(() => approveEventMessage(eventMessageId, message.row_version))
          }
        />
        <ActionButton
          label="즉시 발행"
          visible={canTransition(message.status, "PUBLISHED")}
          busy={busy}
          onClick={() =>
            runAction(() => publishEventMessage(eventMessageId, message.row_version))
          }
        />
        <ScheduleButton
          visible={canTransition(message.status, "SCHEDULED")}
          busy={busy}
          onSchedule={(scheduledAtIso) =>
            runAction(() => scheduleEventMessage(eventMessageId, message.row_version, scheduledAtIso))
          }
        />
        <CancelButton
          visible={canTransition(message.status, "CANCELLED")}
          busy={busy}
          onCancel={(reason) =>
            runAction(() => cancelEventMessage(eventMessageId, message.row_version, reason))
          }
        />
        <ActionButton
          label="종료 처리"
          visible={canTransition(message.status, "COMPLETED")}
          busy={busy}
          onClick={() =>
            runAction(() => completeEventMessage(eventMessageId, message.row_version))
          }
        />
      </div>

      {preview && <EventMessagePreviewPanel preview={preview} messageType={message.message_type} />}

      {isEditable(message.status) ? (
        <div className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold">수정</h2>
          <p className="text-xs text-[var(--color-text-muted)]">
            {message.status !== "DRAFT" &&
              "내용을 수정하면 미리보기가 무효화되어 다시 초안(DRAFT) 상태로 돌아갑니다."}
          </p>
          <EventMessageForm
            initial={{
              message_type: message.message_type,
              title: message.title,
              body: message.body,
              channels: message.channels,
              target_segment: message.target_segment,
              target_role_code: message.target_role_code,
              destination_screen: message.destination_screen,
              scheduled_at: message.scheduled_at ? message.scheduled_at.slice(0, 16) : "",
            }}
            submitting={busy}
            submitLabel="변경사항 저장"
            onSubmit={submitEdit}
          />
        </div>
      ) : (
        <p className="text-xs text-[var(--color-text-muted)]">
          현재 상태({message.status})에서는 내용을 수정할 수 없습니다.
        </p>
      )}

      <button
        type="button"
        onClick={() => router.push(`/event-messages?event_id=${encodeURIComponent(message.event_id)}`)}
        className="tap-target self-start text-xs text-[var(--color-text-muted)] hover:underline"
      >
        ← 목록으로
      </button>
    </div>
  );
}

function ActionButton({
  label,
  visible,
  busy,
  onClick,
}: {
  label: string;
  visible: boolean;
  busy: boolean;
  onClick: () => void;
}) {
  if (!visible) return null;
  return (
    <button
      type="button"
      disabled={busy}
      onClick={onClick}
      className="tap-target rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-xs font-medium hover:bg-[var(--color-surface-muted)] disabled:opacity-50"
    >
      {label}
    </button>
  );
}

function ScheduleButton({
  visible,
  busy,
  onSchedule,
}: {
  visible: boolean;
  busy: boolean;
  onSchedule: (scheduledAtIso: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  if (!visible) return null;
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="tap-target rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-xs font-medium hover:bg-[var(--color-surface-muted)]"
      >
        예약 발행
      </button>
    );
  }
  return (
    <div className="flex items-center gap-2">
      <input
        aria-label="예약 시각"
        type="datetime-local"
        className="input"
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
      <button
        type="button"
        disabled={busy || !value}
        onClick={() => {
          onSchedule(new Date(value).toISOString());
          setOpen(false);
        }}
        className="tap-target rounded-md bg-[var(--color-brand)] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
      >
        확정
      </button>
    </div>
  );
}

function CancelButton({
  visible,
  busy,
  onCancel,
}: {
  visible: boolean;
  busy: boolean;
  onCancel: (reason: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  if (!visible) return null;
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="tap-target rounded-md border border-[var(--color-danger)] px-3 py-1.5 text-xs font-medium text-[var(--color-danger)] hover:bg-[var(--color-danger-bg)]"
      >
        취소
      </button>
    );
  }
  return (
    <div className="flex items-center gap-2">
      <input
        aria-label="취소 사유"
        className="input"
        placeholder="취소 사유(필수)"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <button
        type="button"
        disabled={busy || !reason.trim()}
        onClick={() => {
          onCancel(reason.trim());
          setOpen(false);
        }}
        className="tap-target rounded-md bg-[var(--color-danger)] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
      >
        취소 확정
      </button>
    </div>
  );
}
