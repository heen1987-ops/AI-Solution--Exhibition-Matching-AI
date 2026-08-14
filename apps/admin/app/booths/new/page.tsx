"use client";

/**
 * 부스 등록 폼 (작업 지시 필수 요구사항).
 *
 * TODO(백엔드 미구현): `POST /admin/booths`는 §40.9절에 문서화조차 되어 있지 않다 -
 * exhibition.booth(apps/api/app/models/exhibitor.py)는 tenant/event/zone/participation
 * 경계 FK가 있어 등록 API가 최소한 이 네 값을 받아야 한다는 것만 확실하다. 이 폼은 그
 * 필드들을 미리 갖춰 두고, 백엔드가 구현되면 lib/api-client.ts의 `createAdminBooth`만
 * 경로 대조 후 그대로 쓸 수 있게 한다. 지금 제출하면 실제 네트워크 호출 후 정직한
 * 오류(404 미구현)를 보여준다.
 */

import { useState } from "react";

import { createAdminBooth } from "@/lib/api-client";
import type { AdminBoothListItem } from "@/lib/types";
import ErrorBanner from "@/components/ErrorBanner";
import Field from "@/components/Field";

export default function NewBoothPage() {
  const [eventId, setEventId] = useState("");
  const [exhibitorId, setExhibitorId] = useState("");
  const [participationId, setParticipationId] = useState("");
  const [boothNumber, setBoothNumber] = useState("");
  const [zoneId, setZoneId] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [created, setCreated] = useState<AdminBoothListItem | null>(null);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    setCreated(null);
    try {
      const booth = await createAdminBooth({
        event_id: eventId,
        exhibitor_id: exhibitorId,
        participation_id: participationId,
        booth_number: boothNumber,
        zone_id: zoneId || null,
      });
      setCreated(booth);
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex max-w-2xl flex-col gap-4">
      <h1 className="text-xl font-semibold">부스 등록</h1>
      {error ? <ErrorBanner error={error} /> : null}
      {created && (
        <p className="rounded-md border border-[var(--color-success)] bg-[var(--color-success-bg)] p-2 text-sm text-[var(--color-success)]">
          등록되었습니다: {created.booth_number}
        </p>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
        className="flex flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4"
      >
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="행사 ID" required hint="UUID">
            <input required value={eventId} onChange={(e) => setEventId(e.target.value)} className="input font-mono text-xs" />
          </Field>
          <Field label="업체 ID" required hint="UUID">
            <input required value={exhibitorId} onChange={(e) => setExhibitorId(e.target.value)} className="input font-mono text-xs" />
          </Field>
          <Field label="참가신청 ID" required hint="UUID (exhibitor_participation)">
            <input required value={participationId} onChange={(e) => setParticipationId(e.target.value)} className="input font-mono text-xs" />
          </Field>
          <Field label="구역 ID" hint="UUID, 선택">
            <input value={zoneId} onChange={(e) => setZoneId(e.target.value)} className="input font-mono text-xs" />
          </Field>
        </div>
        <Field label="부스번호" required hint="예: B-12">
          <input required value={boothNumber} onChange={(e) => setBoothNumber(e.target.value)} className="input" />
        </Field>

        <button
          type="submit"
          disabled={submitting}
          className="tap-target w-fit rounded-md bg-[var(--color-brand)] px-4 py-2 text-sm font-medium text-[var(--color-brand-contrast)] disabled:opacity-50"
        >
          {submitting ? "등록 중…" : "등록"}
        </button>
      </form>
    </div>
  );
}
