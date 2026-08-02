import Link from "next/link";
import { findMockExhibitorById, MOCK_EXHIBITORS } from "@/lib/mock/exhibitors";

/**
 * K-S5 업체·부스 상세 화면 골격.
 *
 * K-3-screen-ia.md §1: 웹의 S-5와 콘텐츠는 공유하되 화면 구현은 독립적이다.
 * 이번 웨이브는 Mock 데이터만 사용하고, "QR로 모바일 이어보기"는 K-S7로
 * 이동하는 자리표시자 버튼만 둔다(실제 QR 발급/세션 인계는 이후 웨이브, K-5).
 */
export interface ExhibitorDetailScreenProps {
  exhibitorId?: string;
}

export function ExhibitorDetailScreen({
  exhibitorId,
}: ExhibitorDetailScreenProps) {
  const exhibitor =
    (exhibitorId ? findMockExhibitorById(exhibitorId) : undefined) ??
    MOCK_EXHIBITORS[0];

  return (
    <main
      data-testid="screen-exhibitor-detail"
      className="flex min-h-screen flex-col gap-6 bg-slate-950 px-8 py-16 text-white"
    >
      <Link href="/results" className="text-sm text-slate-400">
        ← 목록으로
      </Link>

      <header>
        <p className="text-sm uppercase tracking-widest text-slate-400">
          {exhibitor.category}
        </p>
        <h1 className="text-kiosk-lg font-bold">{exhibitor.name}</h1>
        <p className="mt-1 text-kiosk text-slate-300">
          {exhibitor.zone} · 부스 {exhibitor.boothCode}
        </p>
      </header>

      <p className="max-w-2xl text-kiosk text-slate-200">{exhibitor.summary}</p>

      <div className="mt-auto flex gap-4">
        <Link
          href="/map"
          className="min-h-touch flex-1 rounded-2xl bg-slate-800 px-6 py-4 text-center text-kiosk font-semibold"
        >
          지도에서 보기
        </Link>
        <Link
          href="/qr"
          className="min-h-touch flex-1 rounded-2xl bg-emerald-500 px-6 py-4 text-center text-kiosk font-semibold text-slate-950"
        >
          QR로 모바일에서 이어보기
        </Link>
      </div>
    </main>
  );
}
