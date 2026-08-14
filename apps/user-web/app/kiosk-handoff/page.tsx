"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

interface PublicProduct {
  product_id: string;
  product_name: string;
  product_summary: string | null;
  alcohol_percentage: number | null;
  retail_price_amount: number | null;
  event_price_amount: number | null;
  currency: string;
  tasting_status: string;
  purchase_status: string;
}

interface PublicBooth {
  booth_id: string;
  booth_number: string;
  operating_status: string;
  estimated_wait_minutes: number | null;
  zone: { zone_name: string } | null;
}

interface PublicSelection extends PublicBooth {
  exhibitor_id: string;
  company_name: string;
  company_summary: string | null;
  products: PublicProduct[];
}

interface ResolveResponse {
  handoff_id: string;
  event_id: string;
  selected_results: PublicSelection[];
  expires_at: string;
  claimed_at: string;
}

interface ApiEnvelope<T> {
  success: true;
  data: T;
}

const API_ORIGIN = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/+$/, "");

async function resolveHandoff(token: string, signal: AbortSignal): Promise<ResolveResponse> {
  const response = await fetch(`${API_ORIGIN}/api/v1/kiosk/handoffs/resolve`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    credentials: "omit",
    cache: "no-store",
    body: JSON.stringify({ token }),
    signal,
  });
  const payload = (await response.json().catch(() => null)) as
    | ApiEnvelope<ResolveResponse>
    | { detail?: { message?: string } }
    | null;
  if (!response.ok || !payload || !("success" in payload) || payload.success !== true) {
    const message =
      payload && "detail" in payload
        ? payload.detail?.message
        : undefined;
    throw new Error(message ?? "QR이 만료되었거나 올바르지 않습니다.");
  }
  return payload.data;
}

function HandoffContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const [data, setData] = useState<ResolveResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setError("QR 인계 정보가 없습니다.");
      return;
    }
    const controller = new AbortController();
    resolveHandoff(token, controller.signal)
      .then(setData)
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : "QR을 확인하지 못했습니다.");
      });
    return () => controller.abort();
  }, [token]);

  if (error) {
    return (
      <section className="mx-auto flex min-h-[60dvh] max-w-md flex-col items-center justify-center px-5 text-center">
        <div className="flex h-20 w-20 items-center justify-center rounded-full bg-red-100 text-3xl" aria-hidden="true">
          !
        </div>
        <h1 className="mt-5 text-2xl font-bold">QR 정보를 열 수 없어요</h1>
        <p className="mt-3 text-base" style={{ color: "var(--color-text-muted)" }}>{error}</p>
        <Link href="/home" className="tap-target mt-7 rounded-xl bg-brand-600 px-6 py-3 font-bold text-white">
          홈으로 이동
        </Link>
      </section>
    );
  }

  if (!data) {
    return (
      <div className="flex min-h-[60dvh] items-center justify-center" role="status" aria-live="polite">
        <p className="text-lg font-semibold">선택한 업체 정보를 불러오는 중…</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-screen-content px-4 py-7 sm:px-6">
      <header className="rounded-2xl bg-brand-50 p-5 dark:bg-stone-800">
        <p className="text-sm font-semibold text-brand-700 dark:text-brand-300">키오스크에서 보낸 정보</p>
        <h1 className="mt-1 text-3xl font-black">선택한 업체를 휴대폰에 담았어요</h1>
        <p className="mt-2 text-sm" style={{ color: "var(--color-text-muted)" }}>
          QR 유효시간: {new Date(data.expires_at).toLocaleString("ko-KR")}
        </p>
      </header>

      {data.selected_results.length === 0 ? (
        <p className="mt-8 rounded-2xl bg-white p-6 text-center shadow-sm dark:bg-stone-800">
          현재 공개 중인 업체 정보가 없습니다.
        </p>
      ) : (
        <div className="mt-6 grid gap-5">
          {data.selected_results.map((selection) => (
            <article key={selection.booth_id} className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-stone-200 dark:bg-stone-800 dark:ring-stone-700">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-semibold text-brand-700 dark:text-brand-300">
                    {selection.zone?.zone_name ? `${selection.zone.zone_name} · ` : ""}
                    {selection.booth_number}
                  </p>
                  <h2 className="mt-1 text-2xl font-bold">{selection.company_name}</h2>
                </div>
                <span className="rounded-full bg-emerald-100 px-3 py-1 text-sm font-semibold text-emerald-800">
                  {selection.operating_status === "OPEN" ? "운영 중" : "잠시 중단"}
                </span>
              </div>
              {selection.company_summary && (
                <p className="mt-3" style={{ color: "var(--color-text-muted)" }}>
                  {selection.company_summary}
                </p>
              )}
              {selection.products.length > 0 && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {selection.products.map((product) => (
                    <span key={product.product_id} className="rounded-full bg-stone-100 px-3 py-1 text-sm dark:bg-stone-700">
                      {product.product_name}
                    </span>
                  ))}
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

/** 로그인 없이 키오스크 QR을 확인하는 모바일 게스트 화면. */
export default function KioskHandoffPage() {
  return (
    <Suspense fallback={null}>
      <HandoffContent />
    </Suspense>
  );
}
