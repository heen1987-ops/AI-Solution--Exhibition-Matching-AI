"use client";

import { useMemo, useState } from "react";

import NaverVenueMap from "@/components/NaverVenueMap";
import {
  buildNaverRouteUrl,
  detectNaverLaunchTarget,
  EXCO_WEST_EXHIBITION_HALL,
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

function IconWalk() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <circle cx="13" cy="4" r="2" />
      <path d="m10 22 1.5-7-3-2 2-5 4 2 3 3M11.5 15l4 2 2 5M8.5 13 5 16" />
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
      <NaverVenueMap />

      <div className="p-5 md:p-7">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="backju-eyebrow text-brand-600">행사장 오는 길</p>
            <h2 id="venue-directions-heading" className="mt-2 text-2xl font-black tracking-[-0.03em] text-[#302f2c] md:text-3xl">
              {EXCO_WEST_EXHIBITION_HALL.name}
            </h2>
            <p className="mt-2 text-sm text-[var(--color-text-muted)]">
              {EXCO_WEST_EXHIBITION_HALL.address} · 행사장: {EXCO_WEST_EXHIBITION_HALL.eventHall}
            </p>
          </div>
          <span className="rounded-full bg-[#cde2cd] px-3 py-1 text-xs font-bold text-[#294b2d]">도착지 고정</span>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-3">
          <button
            type="button"
            onClick={() => openDirections("walk")}
            className="tap-target justify-start gap-3 rounded-sm bg-[#cde2cd] px-4 py-4 text-left font-extrabold text-[#294b2d] transition hover:brightness-95 disabled:cursor-wait disabled:opacity-70"
            disabled={launchState === "opening"}
          >
            <span className="h-7 w-7"><IconWalk /></span>
            <span><strong className="block">도보 길찾기</strong><small className="font-medium">현재 위치 → EXCO 서관 전시장</small></span>
          </button>
          <button
            type="button"
            onClick={() => openDirections("public")}
            className="tap-target justify-start gap-3 rounded-sm bg-[#93c0df] px-4 py-4 text-left font-extrabold text-[#1f3543] transition hover:brightness-95 disabled:cursor-wait disabled:opacity-70"
            disabled={launchState === "opening"}
          >
            <span className="h-7 w-7"><IconBus /></span>
            <span><strong className="block">대중교통 길찾기</strong><small className="font-medium">현재 위치 → EXCO 서관 전시장</small></span>
          </button>
          <button
            type="button"
            onClick={() => openDirections("car")}
            className="tap-target justify-start gap-3 rounded-sm bg-[#ef98a1] px-4 py-4 text-left font-extrabold text-[#4d292d] transition hover:brightness-95 disabled:cursor-wait disabled:opacity-70"
            disabled={launchState === "opening"}
          >
            <span className="h-7 w-7"><IconCar /></span>
            <span><strong className="block">차량 길찾기</strong><small className="font-medium">현재 위치 → EXCO 서관 전시장</small></span>
          </button>
        </div>

        <p className="mt-5 text-base leading-7 text-[#4d4a43]">
          지도에서 행사장과 현재 위치를 확인할 수 있습니다. 실제 도보·대중교통·차량 경로는 교통수단을 선택하면 네이버 지도의 길찾기 화면에서 이어집니다.
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
