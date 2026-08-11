"use client";

/**
 * 공통 필터 바 — 행사 ID / 기간 프리셋(오늘·행사기간·최근7일·직접지정) / 채널.
 * 상태는 페이지가 소유하고, 이 컴포넌트는 변경 콜백만 올린다.
 *
 * 행사 선택은 행사 목록 API(GET /admin/events)가 아직 백엔드에 없어(lib/api-client.ts
 * TODO 참고) 자유 입력 필드로 둔다 — 행사 API가 등록되면 셀렉트로 교체할 것.
 */

import { DATE_RANGE_PRESET_LABELS } from "../logic";
import type { AnalyticsFilter, ChannelFilter, DateRangePreset } from "../types";

const CHANNEL_LABELS: Record<ChannelFilter, string> = {
  ALL: "전체 채널",
  WEB: "웹",
  KIOSK: "키오스크",
};

export default function AnalyticsFilterBar({
  filter,
  onChange,
  showChannel = true,
}: {
  filter: AnalyticsFilter;
  onChange: (next: AnalyticsFilter) => void;
  showChannel?: boolean;
}) {
  return (
    <div className="flex flex-wrap items-end gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
      <label className="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
        행사 ID
        <input
          type="text"
          value={filter.eventId}
          onChange={(e) => onChange({ ...filter, eventId: e.target.value })}
          placeholder="event_id (UUID)"
          className="w-72 rounded-md border border-[var(--color-border)] bg-transparent px-2 py-1.5 text-sm text-[var(--color-text)]"
        />
      </label>

      <label className="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
        기간
        <select
          value={filter.preset}
          onChange={(e) => onChange({ ...filter, preset: e.target.value as DateRangePreset })}
          className="rounded-md border border-[var(--color-border)] bg-transparent px-2 py-1.5 text-sm text-[var(--color-text)]"
        >
          {(Object.keys(DATE_RANGE_PRESET_LABELS) as DateRangePreset[]).map((preset) => (
            <option key={preset} value={preset}>
              {DATE_RANGE_PRESET_LABELS[preset]}
            </option>
          ))}
        </select>
      </label>

      {filter.preset === "CUSTOM" ? (
        <>
          <label className="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
            시작일
            <input
              type="date"
              value={filter.customStart ?? ""}
              onChange={(e) => onChange({ ...filter, customStart: e.target.value || null })}
              className="rounded-md border border-[var(--color-border)] bg-transparent px-2 py-1.5 text-sm text-[var(--color-text)]"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
            종료일
            <input
              type="date"
              value={filter.customEnd ?? ""}
              onChange={(e) => onChange({ ...filter, customEnd: e.target.value || null })}
              className="rounded-md border border-[var(--color-border)] bg-transparent px-2 py-1.5 text-sm text-[var(--color-text)]"
            />
          </label>
        </>
      ) : null}

      {showChannel ? (
        <label className="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
          채널
          <select
            value={filter.channel}
            onChange={(e) => onChange({ ...filter, channel: e.target.value as ChannelFilter })}
            className="rounded-md border border-[var(--color-border)] bg-transparent px-2 py-1.5 text-sm text-[var(--color-text)]"
          >
            {(Object.keys(CHANNEL_LABELS) as ChannelFilter[]).map((channel) => (
              <option key={channel} value={channel}>
                {CHANNEL_LABELS[channel]}
              </option>
            ))}
          </select>
        </label>
      ) : null}
    </div>
  );
}
