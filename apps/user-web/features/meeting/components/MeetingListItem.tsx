"use client";

import Link from "next/link";

import { nextActionFor } from "../logic";
import type { MeetingResponse } from "../types";

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("ko-KR", { month: "long", day: "numeric" });
}

export default function MeetingListItem({ meeting }: { meeting: MeetingResponse }) {
  const action = nextActionFor(meeting);
  return (
    <li
      className="flex items-center justify-between gap-3 rounded-lg border p-3 text-sm"
      style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
    >
      <div className="flex flex-col gap-1">
        <span className="font-medium">업체 ID {meeting.exhibitor_id}</span>
        <span style={{ color: "var(--color-text-muted)" }}>
          {meeting.topic_code ?? "주제 미정"} · {formatDate(meeting.created_at)}
        </span>
      </div>
      {action ? (
        <Link
          href={action.href}
          className="tap-target inline-flex items-center rounded-lg border px-4 py-2 text-sm font-semibold"
          style={{ borderColor: "var(--color-border)" }}
        >
          {action.label}
        </Link>
      ) : null}
    </li>
  );
}
