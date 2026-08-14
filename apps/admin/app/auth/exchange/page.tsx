"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";

import { authApiUrl } from "@/lib/auth-state";

function ExchangeForm() {
  const params = useSearchParams();
  const router = useRouter();
  const [token, setToken] = useState(params.get("token") ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const attempted = useRef(false);

  const exchange = useCallback(async (value: string) => {
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    window.history.replaceState({}, "", "/auth/exchange");
    try {
      const response = await fetch(authApiUrl("/auth/magic-links/exchange"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ token: value }),
      });
      const payload = (await response.json()) as {
        state?: string;
        message?: string;
      };
      if (!response.ok) throw new Error(payload.message ?? "접근 링크가 유효하지 않습니다.");
      router.replace(payload.state === "AUTHENTICATED" ? "/dashboard" : "/auth/mfa");
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "로그인에 실패했습니다.");
      setBusy(false);
    }
  }, [busy, router]);

  useEffect(() => {
    const initial = params.get("token");
    if (initial && !attempted.current) {
      attempted.current = true;
      void exchange(initial);
    }
  }, [exchange, params]);

  return (
    <main className="mx-auto flex min-h-screen max-w-lg flex-col justify-center gap-5 p-6">
      <div>
        <h1 className="text-2xl font-semibold">관리자 접근 링크 확인</h1>
        <p className="mt-2 text-sm text-[var(--color-text-muted)]">
          알림톡·이메일로 받은 1회용 링크를 서버 세션으로 교환합니다.
        </p>
      </div>
      <label className="text-sm font-medium" htmlFor="access-token">
        접근 토큰
      </label>
      <input
        id="access-token"
        type="password"
        autoComplete="one-time-code"
        value={token}
        onChange={(event) => setToken(event.target.value)}
        className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2"
      />
      {error ? <p role="alert" className="text-sm text-[var(--color-danger)]">{error}</p> : null}
      <button
        type="button"
        disabled={busy || token.length < 22}
        onClick={() => void exchange(token)}
        className="tap-target rounded-md bg-[var(--color-brand)] px-4 py-3 font-medium text-[var(--color-brand-contrast)] disabled:opacity-50"
      >
        {busy ? "확인 중…" : "안전한 세션 시작"}
      </button>
    </main>
  );
}

export default function ExchangePage() {
  return (
    <Suspense fallback={<main className="p-6">접근 링크 확인 중…</main>}>
      <ExchangeForm />
    </Suspense>
  );
}
