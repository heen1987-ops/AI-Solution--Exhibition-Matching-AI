"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import MyEventDashboard from "@/components/MyEventDashboard";
import { apiPost } from "@/lib/api-client";
import { applyVerifiedSession, ensureRuntimeCsrfToken } from "@/lib/auth-state";

type AuthSessionResponse = {
  csrf_token: string;
  principal: { subject_id: string };
};

type LandingState = "VERIFYING" | "READY" | "INVALID";

export function PersonalAccessLanding({
  eventSlug,
}: {
  eventSlug: string;
}) {
  const [state, setState] = useState<LandingState>("VERIFYING");
  const returnPath = `/e/${eventSlug}/my`;

  useEffect(() => {
    let active = true;

    async function establishSession() {
      try {
        const token = new URLSearchParams(window.location.search).get("token");
        if (token) {
          const session = await apiPost<AuthSessionResponse>("/auth/magic-links/exchange", {
            token,
            return_path: returnPath,
          });
          applyVerifiedSession(session);
          window.history.replaceState({}, "", returnPath);
        } else if (!(await ensureRuntimeCsrfToken())) {
          throw new Error("verified session required");
        }
        if (active) setState("READY");
      } catch {
        if (active) setState("INVALID");
      }
    }

    void establishSession();
    return () => {
      active = false;
    };
  }, [returnPath]);

  if (state === "VERIFYING") {
    return <main className="mx-auto min-h-screen max-w-md px-5 py-16">맞춤 정보를 불러오고 있어요.</main>;
  }

  if (state === "INVALID") {
    return (
      <main className="mx-auto min-h-screen max-w-md px-5 py-16">
        <h1 className="text-2xl font-bold">링크를 다시 확인해 주세요</h1>
        <p className="mt-3 text-sm text-slate-600">
          사용했거나 만료된 링크입니다. 새 안내 링크를 받거나 일반 검색을 이용해 주세요.
        </p>
        <Link className="mt-8 inline-flex rounded-xl bg-slate-900 px-5 py-3 text-white" href="/explore">
          업체 검색하기
        </Link>
      </main>
    );
  }

  return <MyEventDashboard />;
}
