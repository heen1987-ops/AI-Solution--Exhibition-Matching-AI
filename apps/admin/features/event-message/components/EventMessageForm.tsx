"use client";

/**
 * 이벤트 메시지 작성/수정 폼. 생성과 수정 양쪽에서 재사용한다(`initial`이 있으면 수정 모드).
 * 클라이언트 측 콘텐츠 검사(`../logic.ts::findContentIssues`)는 1차 피드백일 뿐이며, 실제
 * 저장은 언제나 서버 검증(`apps/api/app/services/event_message/content.py`)을 통과해야
 * 한다 - 여기서 경고가 없다고 해서 저장이 보장되지는 않는다(화면에도 그렇게 안내한다).
 */

import { useMemo, useState } from "react";

import Field from "@/components/Field";

import { findContentIssues } from "../logic";
import TargetSegmentPicker from "./TargetSegmentPicker";
import {
  CHANNELS,
  CHANNEL_LABEL_KO,
  MESSAGE_TYPES,
  MESSAGE_TYPE_LABEL_KO,
  type Channel,
  type EventMessageCreateRequest,
  type MessageType,
  type TargetRoleCode,
  type TargetSegment,
} from "../types";

export interface EventMessageFormValue {
  message_type: MessageType;
  title: string;
  body: string;
  channels: Channel[];
  target_segment: TargetSegment;
  target_role_code: TargetRoleCode | null;
  destination_screen: string;
  scheduled_at: string; // datetime-local 문자열, 빈 값이면 즉시발행 의도
}

const EMPTY_VALUE: EventMessageFormValue = {
  message_type: "EVENT_OPERATION_NOTICE",
  title: "",
  body: "",
  channels: ["IN_APP"],
  target_segment: "ALL_REGISTERED_USERS",
  target_role_code: null,
  destination_screen: "/notifications",
  scheduled_at: "",
};

export default function EventMessageForm({
  initial,
  submitting,
  submitLabel = "저장",
  onSubmit,
}: {
  initial?: Partial<EventMessageFormValue>;
  submitting?: boolean;
  submitLabel?: string;
  onSubmit: (value: EventMessageFormValue) => void;
}) {
  const [value, setValue] = useState<EventMessageFormValue>({ ...EMPTY_VALUE, ...initial });

  const contentIssues = useMemo(() => findContentIssues(value.body), [value.body]);
  const destinationValid = value.destination_screen.startsWith("/") &&
    !value.destination_screen.startsWith("//") &&
    !value.destination_screen.includes("://");

  const canSubmit =
    value.title.trim().length > 0 &&
    value.body.trim().length > 0 &&
    value.channels.length > 0 &&
    destinationValid &&
    (value.target_segment !== "SPECIFIC_ROLE" || value.target_role_code !== null);

  const toggleChannel = (channel: Channel) => {
    setValue((prev) => ({
      ...prev,
      channels: prev.channels.includes(channel)
        ? prev.channels.filter((c) => c !== channel)
        : [...prev.channels, channel],
    }));
  };

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!canSubmit) return;
        onSubmit(value);
      }}
    >
      <Field label="메시지 유형" required>
        <select
          aria-label="메시지 유형"
          className="input"
          value={value.message_type}
          onChange={(e) => setValue((v) => ({ ...v, message_type: e.target.value as MessageType }))}
        >
          {MESSAGE_TYPES.map((t) => (
            <option key={t} value={t}>
              {MESSAGE_TYPE_LABEL_KO[t]}
            </option>
          ))}
        </select>
      </Field>

      <Field label="제목" required>
        <input
          aria-label="제목"
          className="input"
          maxLength={200}
          value={value.title}
          onChange={(e) => setValue((v) => ({ ...v, title: e.target.value }))}
        />
      </Field>

      <Field
        label="본문"
        required
        hint="마크다운 또는 안전한 HTML 일부(p, b, strong, i, em, ul, ol, li, br, a, span)만 허용됩니다. <script>, <img>, on* 이벤트 속성, javascript: 링크는 저장 시 거부됩니다."
      >
        <textarea
          aria-label="본문"
          className="input min-h-[140px]"
          value={value.body}
          onChange={(e) => setValue((v) => ({ ...v, body: e.target.value }))}
        />
      </Field>

      {contentIssues.length > 0 && (
        <ul
          role="alert"
          className="flex flex-col gap-1 rounded-md border border-[var(--color-danger)] bg-[var(--color-danger-bg)] p-2 text-xs text-[var(--color-danger)]"
        >
          {contentIssues.map((issue, idx) => (
            <li key={idx}>{issue.message}</li>
          ))}
        </ul>
      )}

      <Field label="채널" required>
        <div className="flex gap-4">
          {CHANNELS.map((channel) => (
            <label key={channel} className="flex items-center gap-1.5 text-sm">
              <input
                type="checkbox"
                checked={value.channels.includes(channel)}
                onChange={() => toggleChannel(channel)}
              />
              {CHANNEL_LABEL_KO[channel]}
            </label>
          ))}
        </div>
      </Field>

      <TargetSegmentPicker
        segment={value.target_segment}
        roleCode={value.target_role_code}
        onChange={(segment, roleCode) =>
          setValue((v) => ({ ...v, target_segment: segment, target_role_code: roleCode }))
        }
      />

      <Field
        label="대상 화면(내부 경로)"
        required
        hint="/로 시작하는 내부 경로만 허용됩니다. 외부 URL은 허용되지 않습니다."
      >
        <input
          aria-label="대상 화면"
          className="input"
          value={value.destination_screen}
          onChange={(e) => setValue((v) => ({ ...v, destination_screen: e.target.value }))}
        />
        {!destinationValid && (
          <p className="text-xs text-[var(--color-danger)]">내부 경로(/로 시작)만 입력하세요.</p>
        )}
      </Field>

      <Field label="예약 발행 시각" hint="비워두면 승인 후 즉시 발행할 수 있습니다.">
        <input
          aria-label="예약 발행 시각"
          type="datetime-local"
          className="input"
          value={value.scheduled_at}
          onChange={(e) => setValue((v) => ({ ...v, scheduled_at: e.target.value }))}
        />
      </Field>

      <button
        type="submit"
        disabled={!canSubmit || submitting}
        className="tap-target self-start rounded-md bg-[var(--color-brand)] px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
      >
        {submitting ? "저장 중…" : submitLabel}
      </button>
    </form>
  );
}

export function formValueToCreateRequest(
  eventId: string,
  value: EventMessageFormValue,
): EventMessageCreateRequest {
  return {
    event_id: eventId,
    message_type: value.message_type,
    title: value.title,
    body: value.body,
    channels: value.channels,
    target_segment: value.target_segment,
    target_role_code: value.target_role_code,
    destination_screen: value.destination_screen,
    scheduled_at: value.scheduled_at ? new Date(value.scheduled_at).toISOString() : null,
  };
}
