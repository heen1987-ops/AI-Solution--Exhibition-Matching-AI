"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { KioskApiError, kioskHandoff } from "@/lib/api-client";
import { copy } from "@/lib/copy";
import { useKioskSession } from "@/lib/kiosk-session-context";

function clampCoordinate(value: number | null, fallback: number): number {
  if (value === null || !Number.isFinite(value)) return fallback;
  return Math.min(94, Math.max(6, value));
}

/** K06 업체 상세 + K07 부스 지도. 검색 결과의 공개 필드만 표시한다. */
export default function ExhibitorDetailPage() {
  const params = useParams<{ exhibitorId: string }>();
  const router = useRouter();
  const { session, language, results, setSession, setHandoff } = useKioskSession();
  const [busy, setBusy] = useState(false);
  const t = copy[language];
  const result = useMemo(
    () => results.find((item) => item.exhibitor_id === params.exhibitorId),
    [params.exhibitorId, results],
  );

  useEffect(() => {
    if (!session) router.replace("/language");
    else if (!result) router.replace("/results");
  }, [result, router, session]);

  if (!session || !result) return null;

  async function createHandoff() {
    if (!session || !result || busy) return;
    const activeSession = session;
    const selectedResult = result;
    setBusy(true);
    try {
      const handoff = await kioskHandoff(activeSession.session_id, [selectedResult.result_id]);
      setHandoff(handoff);
      // QR 발급과 함께 서버의 라이브 세션이 종료된다. QR 화면에 필요한 익명 인계값만 남긴다.
      setSession(null);
      router.push("/handoff");
    } catch (error) {
      if (error instanceof KioskApiError && error.code === "KIOSK_SESSION_EXPIRED") {
        router.push("/session-ended");
        return;
      }
      const message = error instanceof Error ? error.message : "QR을 만들지 못했습니다.";
      router.push(
        `/network-error?from=${encodeURIComponent(`/exhibitors/${selectedResult.exhibitor_id}`)}&message=${encodeURIComponent(message)}`,
      );
    } finally {
      setBusy(false);
    }
  }

  const mapX = clampCoordinate(result.map_x, 50);
  const mapY = clampCoordinate(result.map_y, 50);

  return (
    <div className="mx-auto flex min-h-[100dvh] max-w-screen-content flex-col gap-7 px-5 py-8 sm:px-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <Link
          href="/results"
          className="flex min-h-tap-min items-center rounded-xl bg-white px-5 text-lg font-semibold text-stone-700 shadow-sm ring-1 ring-stone-300 dark:bg-stone-800 dark:text-stone-100 dark:ring-stone-700"
        >
          ← {t.backToResults}
        </Link>
        <span className="rounded-full bg-emerald-100 px-4 py-2 font-semibold text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100">
          {result.operating_status === "OPEN" ? t.openNow : t.paused}
        </span>
      </header>

      <section className="rounded-3xl bg-white p-6 shadow-sm ring-1 ring-stone-200 dark:bg-stone-800 dark:ring-stone-700 sm:p-8">
        <p className="text-lg font-semibold text-brand-600 dark:text-brand-300">
          {result.zone_name ? `${result.zone_name} · ` : ""}{result.booth_number}
        </p>
        <h1 className="mt-2 text-4xl font-black text-stone-900 dark:text-white sm:text-5xl">
          {result.name}
        </h1>
        {result.summary && (
          <p className="mt-4 max-w-3xl text-xl text-stone-600 dark:text-stone-300">
            {result.summary}
          </p>
        )}
      </section>

      <div className="grid gap-6 md:grid-cols-2">
        <section className="rounded-3xl bg-white p-6 shadow-sm ring-1 ring-stone-200 dark:bg-stone-800 dark:ring-stone-700">
          <h2 className="text-2xl font-bold text-stone-900 dark:text-white">{t.whyRecommended}</h2>
          <p className="mt-3 rounded-2xl bg-brand-50 p-4 text-lg text-brand-700 dark:bg-stone-900 dark:text-brand-300">
            {result.reason}
          </p>
          {result.product_names.length > 0 && (
            <>
              <h2 className="mt-6 text-2xl font-bold text-stone-900 dark:text-white">
                {t.productsTitle}
              </h2>
              <div className="mt-3 flex flex-wrap gap-2">
                {result.product_names.map((product) => (
                  <span key={product} className="rounded-full bg-stone-100 px-4 py-2 text-lg dark:bg-stone-700">
                    {product}
                  </span>
                ))}
              </div>
            </>
          )}
        </section>

        <section className="rounded-3xl bg-white p-6 shadow-sm ring-1 ring-stone-200 dark:bg-stone-800 dark:ring-stone-700">
          <h2 className="text-2xl font-bold text-stone-900 dark:text-white">{t.boothMap}</h2>
          <div className="relative mt-4 aspect-[4/3] overflow-hidden rounded-2xl border-4 border-stone-200 bg-[linear-gradient(90deg,transparent_49%,#e7e5e4_50%,transparent_51%),linear-gradient(transparent_49%,#e7e5e4_50%,transparent_51%)] bg-[length:25%_25%] dark:border-stone-700 dark:bg-stone-900">
            <div
              className="absolute flex min-h-tap-min min-w-tap-min -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-brand-600 px-3 text-center text-sm font-black text-white shadow-lg ring-4 ring-white dark:ring-stone-700"
              style={{ left: `${mapX}%`, top: `${mapY}%` }}
            >
              {result.booth_number}
            </div>
          </div>
          <p className="mt-3 text-center text-lg text-stone-600 dark:text-stone-300">
            {result.zone_name ? `${result.zone_name} · ` : ""}{result.booth_number}
          </p>
        </section>
      </div>

      <button
        type="button"
        disabled={busy}
        onClick={() => void createHandoff()}
        className="sticky bottom-4 min-h-[4rem] w-full rounded-2xl bg-brand-600 px-6 text-2xl font-black text-white shadow-xl active:scale-[0.99] disabled:opacity-60"
      >
        {busy ? "…" : t.handoffButton}
      </button>
    </div>
  );
}
