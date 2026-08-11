"use client";

/**
 * 상담 목록 (`/meetings`) - 상태별로 묶어서 보여주고 각 항목에 다음 행동 링크를 붙인다.
 *
 * 근거 문서
 * ---------
 * - docs/user-ia-wireframes.md 6.2절 상담 상태모델, 4.1절 "상담은 별도 탭을 만들지 않고
 *   홈·일정·업체 상세에서 진입한다" - 이 화면은 그 진입점들이 링크를 거는 목적지다(하단
 *   탭에 새 탭을 추가하지 않는다).
 * - 작업 지시: "meeting list grouped by status (requested/time-proposed/confirmed/
 *   rejected/cancelled/completed) with next-action affordances".
 *
 * `apps/user-web/lib/api-client.ts`/`lib/types.ts`는 편집 범위 밖이라 이 화면은
 * `features/meeting/api.ts`·`features/meeting/types.ts`(실제 백엔드 상태값과 1:1)를 쓴다 -
 * 근거는 `features/meeting/types.ts` 모듈 docstring 참고.
 */

import { useCallback, useEffect, useState } from "react";

import { ApiClientError } from "@/lib/api-client";

import { listMeetings } from "@/features/meeting/api";
import MeetingListItem from "@/features/meeting/components/MeetingListItem";
import { groupMeetingsByStatus } from "@/features/meeting/logic";
import type { MeetingResponse } from "@/features/meeting/types";

export default function MeetingListPage() {
  const [meetings, setMeetings] = useState<MeetingResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const result = await listMeetings();
      setMeetings(result.items);
    } catch (err) {
      setLoadError(err instanceof ApiClientError ? err.message : "상담 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div className="mx-auto max-w-screen-content px-4 py-6">
        <p style={{ color: "var(--color-text-muted)" }}>불러오는 중...</p>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="mx-auto flex max-w-screen-content flex-col gap-3 px-4 py-6">
        <p role="alert" style={{ color: "var(--color-danger)" }}>
          {loadError}
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

  const groups = groupMeetingsByStatus(meetings);

  return (
    <div className="mx-auto flex max-w-screen-content flex-col gap-6 px-4 py-6">
      <header>
        <h1 className="text-xl font-bold">상담</h1>
      </header>

      {groups.length === 0 ? (
        <p style={{ color: "var(--color-text-muted)" }}>아직 요청한 상담이 없습니다.</p>
      ) : (
        groups.map((group) => (
          <section key={group.status} aria-labelledby={`meeting-group-${group.status}`} className="flex flex-col gap-2">
            <h2 id={`meeting-group-${group.status}`} className="text-base font-semibold">
              {group.label} ({group.items.length})
            </h2>
            <ul className="flex flex-col gap-2">
              {group.items.map((meeting) => (
                <MeetingListItem key={meeting.meeting_id} meeting={meeting} />
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  );
}
