"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

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

  return (
    <main className="mx-auto min-h-screen max-w-md px-5 py-12">
      <p className="text-sm font-semibold text-emerald-700">사전등록 정보 연결 완료</p>
      <h1 className="mt-2 text-3xl font-bold tracking-tight">나에게 맞는 전시회를 시작하세요</h1>
      <p className="mt-3 text-slate-600">추천 업체를 확인하고 관심 목록과 방문 일정을 한곳에서 관리할 수 있어요.</p>
      <nav className="mt-8 grid gap-3" aria-label="개인화 메뉴">
        <Link className="rounded-2xl border border-slate-200 p-5 font-semibold" href="/recommendations">
          맞춤 추천 보기
        </Link>
        <Link className="rounded-2xl border border-slate-200 p-5 font-semibold" href="/saved">
          관심 업체 보기
        </Link>
        <Link className="rounded-2xl border border-slate-200 p-5 font-semibold" href="/schedule">
          방문 일정 보기
        </Link>
      </nav>
    </main>
  );
}
