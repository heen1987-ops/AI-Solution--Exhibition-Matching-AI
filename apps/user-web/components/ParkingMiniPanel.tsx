"use client";

import { useState } from "react";

const PARKING_LOTS = [
  {
    name: "서관 1주차장",
    description: "서관 1층 3홀 방문 시 먼저 확인할 주차장",
  },
  {
    name: "서관 2주차장",
    description: "1주차장 혼잡 시 함께 확인할 서관 주차장",
  },
] as const;

const NAVER_PARKING_SEARCH = `https://map.naver.com/p/search/${encodeURIComponent("EXCO 서관 주차장")}`;

export default function ParkingMiniPanel() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        aria-expanded={open}
        aria-controls="parking-mini-panel"
        onClick={() => setOpen(true)}
        className="tap-target rounded-sm border border-[var(--color-border)] px-4 font-bold text-[#4d4a43] transition hover:border-brand-300 hover:text-brand-700"
      >
        주차시설 바로보기
      </button>

      {open ? (
        <div
          id="parking-mini-panel"
          role="dialog"
          aria-modal="false"
          aria-labelledby="parking-mini-title"
          className="fixed inset-x-3 bottom-[5.75rem] z-[70] mx-auto max-w-lg border border-[#b7a578] bg-[#fffdf8] p-5 text-left shadow-[0_20px_54px_rgba(48,45,39,0.3)] md:bottom-6"
        >
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="backju-eyebrow text-brand-600">PARKING · EXCO WEST</p>
              <h3 id="parking-mini-title" className="mt-1 text-xl font-black text-[#302f2c]">서관 3홀 주차 안내</h3>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="주차 안내 닫기"
              className="flex h-8 w-8 flex-none items-center justify-center rounded-full text-xl font-black text-[#665f50] transition hover:bg-black/5"
            >
              ×
            </button>
          </div>

          <p className="mt-3 border-l-4 border-[#d6b168] bg-[#faf7f0] px-3 py-2 text-sm leading-6 text-[#565047]">
            목적지는 <strong>EXCO 서관 1층 3홀</strong>입니다. 주소는 대구광역시 북구 엑스코로 10입니다.
          </p>

          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            {PARKING_LOTS.map((lot, index) => (
              <div key={lot.name} className="border border-[var(--color-border)] bg-white p-3">
                <span className="text-[0.65rem] font-black tracking-[0.12em] text-brand-600">P{index + 1}</span>
                <strong className="mt-1 block text-sm text-[#302f2c]">{lot.name}</strong>
                <p className="mt-1 text-xs leading-5 text-[var(--color-text-muted)]">{lot.description}</p>
              </div>
            ))}
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <p className="max-w-xs text-xs leading-5 text-[var(--color-text-muted)]">
              실시간 혼잡도, 주차 가능 여부와 요금은 방문일 EXCO 현장 안내를 기준으로 확인해 주세요.
            </p>
            <a
              href={NAVER_PARKING_SEARCH}
              target="_blank"
              rel="noreferrer"
              className="tap-target rounded-sm bg-[#03c75a] px-4 text-xs font-extrabold text-white"
            >
              네이버 지도에서 주차장 보기
            </a>
          </div>
        </div>
      ) : null}
    </>
  );
}
