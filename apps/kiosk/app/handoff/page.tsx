"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toCanvas } from "qrcode";

import { copy } from "@/lib/copy";
import { useKioskSession } from "@/lib/kiosk-session-context";

/** K08 서명·만료 QR 인계. QR에는 백엔드가 발급한 익명 handoff URL만 들어간다. */
export default function HandoffPage() {
  const router = useRouter();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const { handoff, language, resetAll } = useKioskSession();
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [qrError, setQrError] = useState(false);
  const t = copy[language];

  useEffect(() => {
    if (!handoff) {
      router.replace("/");
      return;
    }
    const update = () => {
      const remaining = Math.max(
        0,
        Math.ceil((new Date(handoff.expires_at).getTime() - Date.now()) / 1000),
      );
      setSecondsLeft(remaining);
      if (remaining === 0) {
        resetAll({ notifyServer: false });
        router.replace("/session-ended");
      }
    };
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [handoff, resetAll, router]);

  useEffect(() => {
    if (!handoff || !canvasRef.current) return;
    void toCanvas(canvasRef.current, handoff.handoff_url, {
      width: 420,
      margin: 2,
      errorCorrectionLevel: "M",
      color: { dark: "#201a12", light: "#ffffff" },
    }).catch(() => setQrError(true));
  }, [handoff]);

  if (!handoff) return null;
  const minutes = Math.floor(secondsLeft / 60);
  const seconds = String(secondsLeft % 60).padStart(2, "0");

  return (
    <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-6 px-6 py-10 text-center">
      <div>
        <h1 className="text-4xl font-black text-stone-900 dark:text-white sm:text-5xl">
          {t.handoffTitle}
        </h1>
        <p className="mt-3 max-w-xl text-xl text-stone-600 dark:text-stone-300">
          {t.handoffHint}
        </p>
      </div>

      <div className="rounded-3xl bg-white p-5 shadow-xl ring-1 ring-stone-200">
        {qrError ? (
          <p className="flex h-[min(70vw,420px)] w-[min(70vw,420px)] items-center justify-center text-stone-700">
            {handoff.handoff_url}
          </p>
        ) : (
          <canvas ref={canvasRef} className="h-auto w-[min(70vw,420px)] max-w-full" />
        )}
      </div>

      <p className="text-lg font-semibold text-brand-700 dark:text-brand-300">
        {t.handoffExpires} {minutes}:{seconds}
      </p>

      <button
        type="button"
        onClick={() => {
          resetAll({ notifyServer: false });
          router.replace("/");
        }}
        className="min-h-tap-min rounded-2xl bg-stone-900 px-8 py-3 text-xl font-bold text-white shadow-md active:scale-95 dark:bg-white dark:text-stone-900"
      >
        {t.backToStart}
      </button>
    </div>
  );
}
