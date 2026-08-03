"use client";

import { useMemo, useState } from "react";

import {
  buildNaverRouteUrl,
  detectNaverLaunchTarget,
  EXCO_HALL_3,
  NAVER_MAP_WEB_FALLBACK,
  type NaverTravelMode,
} from "@/lib/naver-map";

type LaunchState = "idle" | "opening";

function IconBus() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <rect x="4" y="3" width="16" height="16" rx="3" />
      <path d="M4 11h16M8 7h8M7.5 15h.01M16.5 15h.01M7 19v2M17 19v2" />
    </svg>
  );
}

function IconCar() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="m5 11 1.7-5h10.6l1.7 5M4 11h16v7H4zM7 18v2M17 18v2M7.5 14.5h.01M16.5 14.5h.01" />
    </svg>
  );
}

function IconPin() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Z" />
      <circle cx="12" cy="10" r="2.5" />
    </svg>
  );
}

export default function VenueDirections() {
  const [launchState, setLaunchState] = useState<LaunchState>("idle");

  const appName = useMemo(() => {
    if (typeof window === "undefined") return "https://match.backju.kr";
    return window.location.origin;
  }, []);

  const openDirections = (mode: NaverTravelMode) => {
    if (typeof window === "undefined") return;

    setLaunchState("opening");
    const target = detectNaverLaunchTarget(window.navigator.userAgent);
    const routeUrl = buildNaverRouteUrl(mode, target, appName);

    window.location.assign(routeUrl);

    // iOS에서 네이버 지도 앱이 없는 경우에도 사용자가 막히지 않도록 웹 검색 링크를
    // 화면에 항상 남긴다. 강제 앱스토어 이동은 사용자의 맥락을 끊으므로 하지 않는다.
    window.setTimeout(() => setLaunchState("idle"), 1200);
  };

  return (
    <section aria-labelledby="venue-directions-heading" className="overflow-hidden border border-[var(--color-border)] bg-white backju-panel">
      <div className="venue-map-visual" aria-label="대구 EXCO 서관 3홀 도착지 안내">
        <div className="venue-map-grid" aria-hidden="true" />
        <div className="venue-map-route venue-map-route-a" aria-hidden="true" />
        <div className="venue-map-route venue-map-route-b" aria-hidden="true" />
        <div className="venue-map-marker">
          <span className="venue-map-marker-icon"><IconPin /></span>
          <span className="venue-map-marker-copy">
            <strong>도착지</strong>
            <span>EXCO 서관 3홀</span>
          </span>
        </div>
        <div className="venue-map-caption">DAEGU · EXCO WEST WING</div>
      </div>

      <div className="p-5 md:p-7">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="backju-eyebrow text-brand-600">행사장 오는 길</p>
            <h2 id="venue-directions-heading" className="mt-2 text-2xl font-black tracking-[-0.03em] text-[#302f2c] md:text-3xl">
              {EXCO_HALL_3.name}
            </h2>
            <p className="mt-2 text-sm text-[var(--color-text-muted)]">{EXCO_HALL_3.address} · 1층 전시장</p>
          </div>
          <span className="rounded-full bg-[#cde2cd] px-3 py-1 text-xs font-bold text-[#294b2d]">도착지 고정</span>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-2">
          <button
            type="button"
            onClick={() => openDirections("public")}
            className="tap-target justify-start gap-3 rounded-sm bg-[#93c0df] px-4 py-4 text-left font-extrabold text-[#1f3543] transition hover:brightness-95 disabled:cursor-wait disabled:opacity-70"
            disabled={launchState === "opening"}
          >
            <span className="h-7 w-7"><IconBus /></span>
            <span><strong className="block">대중교통 길찾기</strong><small className="font-medium">현재 위치 → EXCO 3홀</small></span>
          </button>
          <button
            type="button"
            onClick={() => openDirections("car")}
            className="tap-target justify-start gap-3 rounded-sm bg-[#ef98a1] px-4 py-4 text-left font-extrabold text-[#4d292d] transition hover:brightness-95 disabled:cursor-wait disabled:opacity-70"
            disabled={launchState === "opening"}
          >
            <span className="h-7 w-7"><IconCar /></span>
            <span><strong className="block">차량 길찾기</strong><small className="font-medium">현재 위치 → EXCO 3홀</small></span>
          </button>
        </div>

        <p className="mt-5 text-base leading-7 text-[#4d4a43]">
          출발지는 네이버 지도가 현재 위치로 설정합니다. 교통수단을 선택하면 별도 입력 없이 EXCO 서관 3홀까지의 경로를 확인할 수 있어요.
        </p>

        <div className="mt-4 flex flex-col gap-2 border-l-4 border-[#eee0b7] bg-[#faf7f0] px-4 py-3 text-sm text-[#5c574f] sm:flex-row sm:items-center sm:justify-between">
          <p><strong className="text-[#3b3935]">위치정보 안내</strong><br />현재 위치는 네이버 지도에서만 사용하며 이 서비스는 수집하거나 저장하지 않습니다.</p>
          <a href={NAVER_MAP_WEB_FALLBACK} target="_blank" rel="noreferrer" className="tap-target flex-none justify-start font-bold text-brand-700 underline underline-offset-4">
            웹에서 장소 보기
          </a>
        </div>
      </div>
    </section>
  );
}
