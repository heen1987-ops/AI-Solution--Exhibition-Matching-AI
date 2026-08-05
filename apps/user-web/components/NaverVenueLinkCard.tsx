import { EXCO_WEST_EXHIBITION_HALL, NAVER_MAP_WEB_FALLBACK } from "@/lib/naver-map";

export default function NaverVenueLinkCard() {
  return (
    <a
      href={NAVER_MAP_WEB_FALLBACK}
      target="_blank"
      rel="noreferrer"
      aria-label="네이버 지도에서 EXCO 서관 전시장 보기"
      className="group relative flex min-h-[280px] flex-col justify-between overflow-hidden bg-[#eef1ec] p-6 text-[#302f2c] transition hover:brightness-[0.98] md:min-h-[340px] md:p-8"
      style={{
        backgroundImage:
          "linear-gradient(135deg, rgba(205,226,205,.88), rgba(255,255,255,.94)), repeating-linear-gradient(45deg, transparent 0 32px, rgba(122,102,61,.08) 32px 34px)",
      }}
    >
      <div className="flex items-start justify-between gap-4">
        <span className="inline-flex h-12 w-12 items-center justify-center bg-[#03c75a] text-2xl font-black text-white">
          N
        </span>
        <span className="rounded-full border border-[#9dbda5] bg-white/80 px-3 py-1 text-xs font-extrabold text-[#294b2d]">
          네이버 지도 연결
        </span>
      </div>

      <div className="max-w-xl bg-white/90 p-5 shadow-[0_14px_38px_rgba(48,45,39,0.12)] backdrop-blur-sm md:p-6">
        <p className="backju-eyebrow text-brand-600">NAVER MAP</p>
        <strong className="mt-2 block text-2xl font-black tracking-[-0.03em] md:text-3xl">
          {EXCO_WEST_EXHIBITION_HALL.name}
        </strong>
        <span className="mt-2 block text-sm leading-6 text-[var(--color-text-muted)]">
          {EXCO_WEST_EXHIBITION_HALL.address} · 행사장: {EXCO_WEST_EXHIBITION_HALL.eventHall}
        </span>
        <span className="tap-target mt-4 inline-flex rounded-sm bg-[#03c75a] px-5 text-sm font-extrabold text-white transition group-hover:bg-[#02b451]">
          네이버 지도에서 보기
        </span>
      </div>
    </a>
  );
}
