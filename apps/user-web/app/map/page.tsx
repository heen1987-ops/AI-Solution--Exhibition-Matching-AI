import type { Metadata } from "next";

import ProvisionalBoothLayout from "@/components/ProvisionalBoothLayout";
import VenueDirections from "@/components/VenueDirections";

export const metadata: Metadata = {
  title: "행사장 오는 길",
  description: "현재 위치에서 대구 EXCO 서관 3홀까지 네이버 지도 길찾기와 행사장 안내를 확인합니다.",
};

const TRANSIT_ROWS = [
  { label: "동대구역", detail: "413 · 순환2-1 · 937번 / 버스 약 30분" },
  { label: "대구국제공항", detail: "버스 환승 약 30분 · 택시 약 20분" },
  { label: "EXCO 정류장", detail: "300 · 304 · 306 · 320 · 413 · 653 · 937 · 북구2" },
] as const;

export default function MapPage() {
  return (
    <div className="mx-auto w-full max-w-screen-content px-4 py-6 md:px-8 md:py-10">
      <header className="mb-6">
        <p className="backju-eyebrow text-brand-600">VISIT · MAP</p>
        <h1 className="backju-section-title mt-2 text-3xl font-black tracking-[-0.04em] text-[#302f2c] md:text-4xl">행사장 오는 길</h1>
        <p className="mt-3 max-w-2xl text-[var(--color-text-muted)]">먼저 EXCO 3홀까지의 이동 경로를 확인하고, 행사장 도착 후 확정된 부스 위치도를 이어서 볼 수 있습니다.</p>
      </header>

      <VenueDirections />

      <div className="mt-6">
        <section aria-labelledby="transit-heading" className="border border-[var(--color-border)] bg-white p-5 backju-panel md:p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="backju-eyebrow text-brand-600">교통 안내</p>
              <h2 id="transit-heading" className="mt-1 text-xl font-black">주요 거점에서 EXCO까지</h2>
            </div>
            <span className="rounded-full bg-brand-50 px-3 py-1 text-xs font-bold text-brand-700">EXCO 공식 안내</span>
          </div>
          <dl className="mt-5 divide-y divide-[var(--color-border)] border-y border-[var(--color-border)]">
            {TRANSIT_ROWS.map((row) => (
              <div key={row.label} className="grid gap-1 py-4 sm:grid-cols-[8rem_1fr] sm:gap-4">
                <dt className="font-extrabold text-[#3b3935]">{row.label}</dt>
                <dd className="text-sm leading-6 text-[var(--color-text-muted)]">{row.detail}</dd>
              </div>
            ))}
          </dl>
          <div className="mt-4 flex flex-wrap gap-3 text-sm">
            <a href="https://www.exco.co.kr/Notification/sub03.html#map001" target="_blank" rel="noreferrer" className="tap-target rounded-sm border border-brand-300 px-4 font-bold text-brand-700">
              EXCO 상세 교통안내
            </a>
            <a href="https://www.exco.co.kr/facility/sub06.html" target="_blank" rel="noreferrer" className="tap-target rounded-sm border border-[var(--color-border)] px-4 font-bold text-[#4d4a43]">
              주차시설 확인
            </a>
          </div>
        </section>
      </div>

      <div className="mt-6">
        <ProvisionalBoothLayout />
      </div>
    </div>
  );
}
