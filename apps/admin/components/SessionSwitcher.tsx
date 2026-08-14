"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ROLE_LABELS, revokeVerifiedSession } from "@/lib/auth-state";
import { useSession } from "@/lib/use-session";

export default function SessionSwitcher() {
  const [session] = useSession();
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  if (session.state === "ANONYMOUS") {
    return (
      <Link href="/auth/exchange" className="tap-target rounded-md border px-3 py-1.5 text-sm">
        관리자 로그인
      </Link>
    );
  }
  if (session.state !== "AUTHENTICATED" || !session.role) {
    return (
      <Link href="/auth/mfa" className="tap-target rounded-md border px-3 py-1.5 text-sm">
        MFA 인증 필요
      </Link>
    );
  }
  return (
    <div className="flex items-center gap-2 text-sm">
      <span>{ROLE_LABELS[session.role]}</span>
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          await revokeVerifiedSession();
          router.push("/auth/exchange");
          router.refresh();
        }}
        className="tap-target rounded-md border px-3 py-1.5 disabled:opacity-50"
      >
        로그아웃
      </button>
    </div>
  );
}
