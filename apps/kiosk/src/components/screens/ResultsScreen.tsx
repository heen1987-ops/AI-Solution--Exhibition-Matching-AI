import Link from "next/link";
import { MOCK_EXHIBITORS, type MockExhibitor } from "@/lib/mock/exhibitors";

/**
 * K-S4 결과 목록 화면 골격.
 *
 * K-3-screen-ia.md §2-1: "검색 결과 없음"은 오류(K-S8)가 아니라 이 화면(K-S4)의
 * 한 상태(empty state)로 처리한다 - 그래서 별도 라우트를 만들지 않고 이 컴포넌트가
 * `exhibitors=[]`를 받았을 때의 상태로 표현한다.
 */
export interface ResultsScreenProps {
  exhibitors?: MockExhibitor[];
}

export function ResultsScreen({
  exhibitors = MOCK_EXHIBITORS,
}: ResultsScreenProps) {
  const isEmpty = exhibitors.length === 0;

  return (
    <main
      data-testid="screen-results"
      className="flex min-h-screen flex-col gap-6 bg-slate-950 px-8 py-16 text-white"
    >
      <header>
        <h1 className="text-kiosk-lg font-bold">검색 결과</h1>
        <p className="mt-1 text-kiosk text-slate-300">
          {isEmpty ? "조건에 맞는 업체를 찾지 못했습니다" : `총 ${exhibitors.length}건`}
        </p>
      </header>

      {isEmpty ? (
        <div
          data-testid="results-empty-state"
          className="flex flex-1 flex-col items-center justify-center gap-4 text-center"
        >
          <p className="text-kiosk text-slate-300">
            검색어를 조금 더 간단히 입력하거나 인기 카테고리를 둘러보세요.
          </p>
          <Link
            href="/search"
            className="min-h-touch rounded-2xl bg-emerald-500 px-8 py-4 text-kiosk font-semibold text-slate-950"
          >
            다시 검색하기
          </Link>
        </div>
      ) : (
        <ul className="flex flex-1 flex-col gap-4">
          {exhibitors.map((exhibitor) => (
            <li key={exhibitor.id}>
              <Link
                href={`/exhibitors/${exhibitor.id}`}
                className="flex min-h-touch flex-col gap-1 rounded-2xl bg-slate-800 px-6 py-4"
              >
                <span className="text-kiosk font-semibold">
                  {exhibitor.name}
                </span>
                <span className="text-sm text-slate-400">
                  {exhibitor.zone} · {exhibitor.boothCode} · {exhibitor.category}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
