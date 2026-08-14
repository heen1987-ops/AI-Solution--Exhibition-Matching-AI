"use client";

/** A01 행사 관리. §43절. core.event CRUD API가 아직 없어(lib/api-client.ts TODO 참고)
 * 목록 조회를 시도하고 실패하면 명확한 오류 상태를 보여준다. */

import { useCallback, useEffect, useState } from "react";

import { createAdminEvent, listAdminEvents } from "@/lib/api-client";
import type { AdminEventItem } from "@/lib/types";
import ErrorBanner from "@/components/ErrorBanner";
import Field from "@/components/Field";
import RoleGate from "@/components/RoleGate";
import StatusBadge from "@/components/StatusBadge";

export default function EventsPage() {
  const [events, setEvents] = useState<AdminEventItem[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    listAdminEvents()
      .then((res) => setEvents(res.items))
      .catch((err) => setError(err))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">행사 관리</h1>
        <RoleGate capability="EVENT_MANAGE">
          <button
            type="button"
            onClick={() => setShowForm((v) => !v)}
            className="tap-target rounded-md bg-[var(--color-brand)] px-3 py-2 text-sm font-medium text-[var(--color-brand-contrast)]"
          >
            {showForm ? "닫기" : "행사 등록"}
          </button>
        </RoleGate>
      </div>

      <RoleGate capability="EVENT_MANAGE">
        {showForm && <EventCreateForm onCreated={load} />}
      </RoleGate>

      {loading && <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>}
      {!loading && error ? <ErrorBanner error={error} onRetry={load} /> : null}
      {!loading && !error && events && events.length === 0 && (
        <p className="text-sm text-[var(--color-text-muted)]">등록된 행사가 없습니다.</p>
      )}
      {!loading && !error && events && events.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--color-surface-muted)] text-xs uppercase text-[var(--color-text-muted)]">
              <tr>
                <th className="px-3 py-2">행사명</th>
                <th className="px-3 py-2">상태</th>
                <th className="px-3 py-2">일정</th>
                <th className="px-3 py-2">장소</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.event_id} className="border-t border-[var(--color-border)]">
                  <td className="px-3 py-2 font-medium">{event.name}</td>
                  <td className="px-3 py-2">
                    <StatusBadge status={event.status} />
                  </td>
                  <td className="px-3 py-2">
                    {event.start_date} ~ {event.end_date}
                  </td>
                  <td className="px-3 py-2">{event.venue_name ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function EventCreateForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [venueName, setVenueName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await createAdminEvent({
        name,
        start_date: startDate,
        end_date: endDate,
        venue_name: venueName || null,
      });
      setName("");
      setStartDate("");
      setEndDate("");
      setVenueName("");
      onCreated();
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
      className="flex flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4"
    >
      {error ? <ErrorBanner error={error} /> : null}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Field label="행사명">
          <input
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="input"
          />
        </Field>
        <Field label="장소">
          <input
            value={venueName}
            onChange={(event) => setVenueName(event.target.value)}
            className="input"
          />
        </Field>
        <Field label="시작일">
          <input
            required
            type="date"
            value={startDate}
            onChange={(event) => setStartDate(event.target.value)}
            className="input"
          />
        </Field>
        <Field label="종료일">
          <input
            required
            type="date"
            value={endDate}
            onChange={(event) => setEndDate(event.target.value)}
            className="input"
          />
        </Field>
      </div>
      <button
        type="submit"
        disabled={submitting}
        className="tap-target w-fit rounded-md bg-[var(--color-brand)] px-4 py-2 text-sm font-medium text-[var(--color-brand-contrast)] disabled:opacity-50"
      >
        {submitting ? "등록 중…" : "등록"}
      </button>
    </form>
  );
}
