"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { copy } from "@/lib/copy";
import { useKioskSession } from "@/lib/kiosk-session-context";

/** K10 네트워크 오류. 재시도 가능한 오류(503/네트워크 단절 등)를 위한 공용 화면 -
 * `?from=`으로 되돌아갈 화면, `?message=`로 서버가 준 사용자용 메시지를 전달받는다. */
function NetworkErrorContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { language, resetAll } = useKioskSession();
  const t = copy[language];

  const from = searchParams.get("from") ?? "/search";
  const message = searchParams.get("message");

  return (
    <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-8 px-6 text-center">
      <div className="flex h-24 w-24 items-center justify-center rounded-full bg-amber-100 text-4xl dark:bg-amber-900">
        ⚠️
      </div>
      <div>
        <h1 className="text-3xl font-bold text-stone-900 dark:text-white sm:text-4xl">
          {t.networkErrorTitle}
        </h1>
        <p className="mt-3 max-w-md text-lg text-stone-500 dark:text-stone-400">
          {message || t.networkErrorHint}
        </p>
      </div>

      <div className="flex flex-col gap-4 sm:flex-row">
        <button
          type="button"
          onClick={() => router.replace(from)}
          className="flex min-h-tap-min items-center justify-center rounded-2xl bg-brand-600 px-8 text-xl font-bold text-white shadow-md active:scale-95"
        >
          {t.retry}
        </button>
        <button
          type="button"
          onClick={() => {
            resetAll({ notifyServer: false });
            router.push("/");
          }}
          className="flex min-h-tap-min items-center justify-center rounded-2xl bg-white px-8 text-xl font-bold text-stone-800 shadow-md ring-1 ring-stone-300 active:scale-95 dark:bg-stone-800 dark:text-stone-100 dark:ring-stone-700"
        >
          {t.backToStart}
        </button>
      </div>
    </div>
  );
}

export default function NetworkErrorPage() {
  return (
    <Suspense fallback={null}>
      <NetworkErrorContent />
    </Suspense>
  );
}
