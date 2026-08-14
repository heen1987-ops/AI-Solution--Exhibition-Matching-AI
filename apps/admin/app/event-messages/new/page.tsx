"use client";

/**
 * 이벤트 메시지 새로 작성. URL: /event-messages/new?event_id={eventId}
 */

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import RoleGate from "@/components/RoleGate";

import { createEventMessage } from "@/features/event-message/api";
import EventMessageForm, {
  formValueToCreateRequest,
  type EventMessageFormValue,
} from "@/features/event-message/components/EventMessageForm";
import TemplatePicker from "@/features/notification-template/components/TemplatePicker";

export default function NewEventMessagePage() {
  return (
    <RoleGate capability="EVENT_MANAGE" fallback={<NoAccessNotice />}>
      <NewBody />
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

function NewBody() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const eventId = searchParams.get("event_id") ?? "";

  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);
  const [templateOverride, setTemplateOverride] = useState<Partial<EventMessageFormValue>>();

  const submit = async (value: EventMessageFormValue) => {
    if (!eventId) {
      setError(new Error("event_id가 필요합니다. 목록 화면에서 행사 ID를 먼저 입력하세요."));
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const created = await createEventMessage(formValueToCreateRequest(eventId, value));
      router.push(`/event-messages/${created.event_message_id}`);
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex max-w-2xl flex-col gap-4">
      <h1 className="text-xl font-semibold">새 이벤트 메시지 작성</h1>
      {!eventId && (
        <ErrorBanner
          error={new Error("URL에 event_id 쿼리 파라미터가 없습니다 (예: ?event_id=...).")}
        />
      )}
      <TemplatePicker
        messageType={templateOverride?.message_type ?? "EVENT_OPERATION_NOTICE"}
        onSelect={(template) =>
          setTemplateOverride({
            message_type: template.message_type,
            title: template.title,
            body: template.body,
            destination_screen: template.destination_screen,
          })
        }
      />
      {error != null && <ErrorBanner error={error} />}
      <EventMessageForm
        key={JSON.stringify(templateOverride)}
        initial={templateOverride}
        submitting={submitting}
        submitLabel="초안 저장"
        onSubmit={submit}
      />
    </div>
  );
}
