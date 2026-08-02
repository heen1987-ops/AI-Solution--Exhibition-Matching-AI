"use client";

/**
 * 개발용 세션 전환기. lib/auth-state.ts 모듈 docstring 참고 - 실제 로그인/MFA API가
 * 아직 없어(ADMIN-001 별도 과제) 관리자가 역할·X-Actor-User-Id를 직접 선택하는 임시
 * 스텁이다. 화면에 "임시" 배지를 명확히 표시해 실제 로그인처럼 오인하지 않게 한다.
 */

import { useId, useState } from "react";

import { ROLE_LABELS } from "@/lib/auth-state";
import { useSession } from "@/lib/use-session";
import type { AdminRole } from "@/lib/types";

const ROLES: AdminRole[] = ["EVENT_ADMIN", "DATA_REVIEWER", "EXHIBITOR_ADMIN"];

export default function SessionSwitcher() {
  const [session, setSession] = useSession();
  const [open, setOpen] = useState(false);
  const panelId = useId();

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        className="tap-target flex items-center gap-2 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm"
      >
        <span className="rounded bg-[var(--color-warning-bg)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--color-warning)]">
          임시세션
        </span>
        <span className="max-w-[220px] truncate">{ROLE_LABELS[session.role]}</span>
      </button>

      {open && (
        <div
          id={panelId}
          className="absolute right-0 z-20 mt-2 w-80 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 shadow-lg"
        >
          <p className="mb-3 text-xs text-[var(--color-text-muted)]">
            실제 관리자 로그인/MFA API가 아직 없습니다(TODO). 아래 값은 개발·검수용으로
            로컬에만 저장되며, apps/api 요청의 <code>X-Actor-User-Id</code> 헤더로 그대로
            전달됩니다.
          </p>

          <label className="mb-1 block text-xs font-medium">역할</label>
          <select
            value={session.role}
            onChange={(event) =>
              setSession({ ...session, role: event.target.value as AdminRole })
            }
            className="mb-3 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-2 text-sm"
          >
            {ROLES.map((role) => (
              <option key={role} value={role}>
                {ROLE_LABELS[role]}
              </option>
            ))}
          </select>

          <label className="mb-1 block text-xs font-medium">표시 이름</label>
          <input
            type="text"
            value={session.displayName}
            onChange={(event) => setSession({ ...session, displayName: event.target.value })}
            className="mb-3 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-2 text-sm"
            placeholder="예: 김운영"
          />

          <label className="mb-1 block text-xs font-medium">
            actor_user_id (UUID, X-Actor-User-Id 헤더값)
          </label>
          <input
            type="text"
            value={session.actorUserId ?? ""}
            onChange={(event) =>
              setSession({ ...session, actorUserId: event.target.value || null })
            }
            className="mb-3 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-2 font-mono text-xs"
            placeholder="00000000-0000-0000-0000-000000000000"
          />

          {session.role === "EXHIBITOR_ADMIN" && (
            <>
              <label className="mb-1 block text-xs font-medium">
                소속 업체 exhibitor_id (UUID)
              </label>
              <input
                type="text"
                value={session.exhibitorId ?? ""}
                onChange={(event) =>
                  setSession({ ...session, exhibitorId: event.target.value || null })
                }
                className="mb-3 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-2 font-mono text-xs"
                placeholder="00000000-0000-0000-0000-000000000000"
              />
            </>
          )}

          <button
            type="button"
            onClick={() => setOpen(false)}
            className="tap-target w-full rounded-md bg-[var(--color-brand)] px-3 py-2 text-sm font-medium text-[var(--color-brand-contrast)]"
          >
            닫기
          </button>
        </div>
      )}
    </div>
  );
}
