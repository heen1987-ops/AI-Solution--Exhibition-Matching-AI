/**
 * 미리보기 패널 - 작업 지시가 명시한 항목을 모두 보여준다: 제목, 본문, 대상 수, 채널,
 * 예약 시각, 대상 화면, 중복 대상 경고, 동의 제외 수.
 *
 * `target_count`가 null이면(소규모 그룹 억제, 서버가 결정) 절대 정확한 수를 계산/추정해
 * 보여주지 않는다 - `preview.target_count_display`(서버가 만든 "5명 미만" 문자열)를 그대로
 * 쓴다.
 */

import { TARGET_SEGMENT_LABEL_KO } from "../logic";
import { CHANNEL_LABEL_KO, MESSAGE_TYPE_LABEL_KO } from "../types";
import type { EventMessagePreview, MessageType } from "../types";

function formatDateTime(value: string | null): string {
  if (!value) return "즉시 발행";
  return new Date(value).toLocaleString("ko-KR");
}

export default function EventMessagePreviewPanel({
  preview,
  messageType,
}: {
  preview: EventMessagePreview;
  messageType?: MessageType;
}) {
  return (
    <div className="flex flex-col gap-4 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">미리보기</h3>
        {messageType && (
          <span className="text-xs text-[var(--color-text-muted)]">
            {MESSAGE_TYPE_LABEL_KO[messageType]}
          </span>
        )}
      </div>

      <div className="rounded-md border border-[var(--color-border)] p-3">
        <p className="text-sm font-semibold">{preview.title}</p>
        <p className="mt-1 whitespace-pre-wrap text-sm text-[var(--color-text-muted)]">
          {preview.body}
        </p>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <dt className="text-[var(--color-text-muted)]">대상 세그먼트</dt>
        <dd>
          {TARGET_SEGMENT_LABEL_KO[preview.target_segment]}
          {preview.target_role_code ? ` (${preview.target_role_code})` : ""}
        </dd>

        <dt className="text-[var(--color-text-muted)]">대상 수</dt>
        <dd className="font-medium" data-testid="target-count-display">
          {preview.target_count_display}
        </dd>

        <dt className="text-[var(--color-text-muted)]">채널</dt>
        <dd>{preview.channels.map((c) => CHANNEL_LABEL_KO[c]).join(", ")}</dd>

        <dt className="text-[var(--color-text-muted)]">예약 시각</dt>
        <dd>{formatDateTime(preview.scheduled_at)}</dd>

        <dt className="text-[var(--color-text-muted)]">대상 화면</dt>
        <dd className="font-mono text-xs">{preview.destination_screen}</dd>

        <dt className="text-[var(--color-text-muted)]">동의 제외 수(이메일)</dt>
        <dd>{preview.consent_excluded_count.toLocaleString("ko-KR")}명</dd>
      </dl>

      {preview.small_audience_warning && (
        <p
          role="alert"
          className="rounded-md border border-[var(--color-warning)] bg-[var(--color-warning-bg)] p-2 text-xs font-medium text-[var(--color-warning)]"
        >
          대상자가 매우 적습니다({preview.target_count_display}). 재식별 위험이 있으니 세그먼트를
          넓히거나 발행 여부를 신중히 검토하세요.
        </p>
      )}

      {preview.duplicate_target_warning && (
        <p
          role="alert"
          className="rounded-md border border-[var(--color-warning)] bg-[var(--color-warning-bg)] p-2 text-xs font-medium text-[var(--color-warning)]"
        >
          동일 유형의 활성 메시지가 이미 {preview.duplicate_target_message_count}건 있습니다.
          동일 대상에게 중복 발송될 수 있습니다.
        </p>
      )}
    </div>
  );
}
