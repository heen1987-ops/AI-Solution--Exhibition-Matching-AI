"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { ApiClientError, createProfileSession } from "@/lib/api-client";
import {
  EVENT_ID,
  EVENT_ID_IS_CONFIGURED,
  saveOnboardingState,
} from "@/lib/onboarding-state";

export default function StartPage() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleStart() {
    if (!EVENT_ID_IS_CONFIGURED) {
      setErrorMessage("행사 설정을 확인한 뒤 다시 시도해 주세요.");
      return;
    }
    setBusy(true);
    setErrorMessage(null);
    try {
      const session = await createProfileSession({
        event_id: EVENT_ID,
        entry_channel: "WEB",
        device_type: "MOBILE_WEB",
        language: "ko-KR",
      });
      saveOnboardingState({
        guestSessionId: session.guest_session_id,
        visitSessionId: session.visit_session_id,
        profileId: session.profile_id,
        minimumAge: session.minimum_age,
        eventStatus: session.event_status,
      });
      if (!session.service_available) {
        setErrorMessage("현재는 맞춤 추천을 시작할 수 없습니다. 일반 검색은 이용할 수 있어요.");
        return;
      }
      router.push("/onboarding/role");
    } catch (error) {
      setErrorMessage(
        error instanceof ApiClientError
          ? error.message
          : "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-[calc(100dvh-var(--top-bar-height)-var(--bottom-nav-height))] w-full max-w-md flex-col justify-center gap-6 px-5 py-10">
      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        <p className="text-sm font-semibold text-emerald-700">설치 없이 바로 시작</p>
        <h1 className="mt-2 text-3xl font-extrabold tracking-tight">나에게 맞는 업체를 찾아보세요</h1>
        <p className="mt-3 text-sm leading-6 text-slate-600">
          관심 분야와 방문 목적을 알려주면 승인된 참가기업 정보에서 맞춤 업체를 추천합니다.
        </p>

        {errorMessage ? (
          <p className="mt-4 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700" role="alert">
            {errorMessage}
          </p>
        ) : null}

        <div className="mt-6 grid gap-3">
          <button
            type="button"
            className="min-h-12 rounded-xl bg-slate-900 px-5 py-3 font-bold text-white disabled:opacity-60"
            disabled={busy}
            onClick={() => void handleStart()}
          >
            {busy ? "준비하고 있어요…" : "AI 추천 시작하기"}
          </button>
          <button
            type="button"
            className="min-h-12 rounded-xl border border-slate-300 px-5 py-3 font-semibold"
            disabled={busy}
            onClick={() => router.push("/explore")}
          >
            로그인 없이 업체 검색
          </button>
        </div>
      </section>

      <section className="rounded-2xl bg-emerald-50 p-5">
        <h2 className="font-bold text-emerald-950">사전등록을 하셨나요?</h2>
        <p className="mt-2 text-sm leading-6 text-emerald-900">
          카카오 알림톡이나 이메일로 받은 ‘나의 전시회’ 링크를 열면 등록 정보와 맞춤 추천이 안전하게 연결됩니다.
        </p>
        <p className="mt-2 text-xs text-emerald-800">전화번호를 이 화면에 다시 입력할 필요가 없습니다.</p>
      </section>
    </main>
  );
}
