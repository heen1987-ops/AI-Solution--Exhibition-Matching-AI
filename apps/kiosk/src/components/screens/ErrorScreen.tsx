"use client";

import Link from "next/link";

/**
 * K-S8 오류화면 골격.
 *
 * K-3-screen-ia.md §2가 정의하는 두 가지 실제 오류 상태
 * (검색결과없음은 K-S4의 상태이므로 여기 포함하지 않음):
 *   2. 네트워크 단절 - 캐시 폴백 실패 시 "일시적으로 검색이 어렵습니다" 안내 후
 *      대기화면으로 자동 복귀.
 *   3. QR 인계 실패 - 재시도 버튼 제공, 반복 실패 시 대기화면 복귀.
 * 이번 웨이브는 실제 재시도/캐시 로직 없이 화면 골격과 문구만 제공한다.
 */
export type KioskErrorVariant = "network" | "qr-handoff" | "generic";

const COPY: Record<KioskErrorVariant, { title: string; body: string }> = {
  network: {
    title: "일시적으로 검색이 어렵습니다",
    body: "네트워크 연결을 확인하는 중입니다. 잠시 후 대기화면으로 돌아갑니다.",
  },
  "qr-handoff": {
    title: "모바일 연결에 실패했습니다",
    body: "QR 인계가 완료되지 않았습니다. 다시 시도하거나 대기화면으로 돌아가세요.",
  },
  generic: {
    title: "일시적인 오류가 발생했습니다",
    body: "잠시 후 다시 시도해주세요.",
  },
};

export interface ErrorScreenProps {
  variant?: KioskErrorVariant;
}

export function ErrorScreen({ variant = "generic" }: ErrorScreenProps) {
  const copy = COPY[variant];

  return (
    <main
      data-testid="screen-error"
      className="flex min-h-screen flex-col items-center justify-center gap-6 bg-slate-950 px-8 py-16 text-center text-white"
    >
      <h1 className="text-kiosk-lg font-bold">{copy.title}</h1>
      <p className="max-w-md text-kiosk text-slate-300">{copy.body}</p>

      <div className="flex gap-4">
        {variant === "qr-handoff" && (
          <Link
            href="/qr"
            className="min-h-touch rounded-2xl bg-emerald-500 px-8 py-4 text-kiosk font-semibold text-slate-950"
          >
            다시 시도
          </Link>
        )}
        <Link
          href="/"
          className="min-h-touch rounded-2xl bg-slate-800 px-8 py-4 text-kiosk font-semibold"
        >
          대기화면으로
        </Link>
      </div>
    </main>
  );
}
