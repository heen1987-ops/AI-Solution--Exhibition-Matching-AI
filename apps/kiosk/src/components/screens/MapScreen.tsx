import Link from "next/link";
import { MOCK_EXHIBITORS } from "@/lib/mock/exhibitors";

/**
 * K-S6 지도 화면 골격.
 *
 * K-3-screen-ia.md §1: 웹에는 대응 화면이 없다(키오스크 독립 화면). K-1/PROJECT_SCOPE.md
 * 제외범위: "정밀 실내 내비게이션"은 개발하지 않는다 - 여기서는 구역(zone) 단위의
 * 단순 배치도 자리표시자만 Mock으로 그린다. 실제 좌표·경로 안내는 범위 밖(K-5에서 논의).
 */
export function MapScreen() {
  const zones = Array.from(new Set(MOCK_EXHIBITORS.map((e) => e.zone)));

  return (
    <main
      data-testid="screen-map"
      className="flex min-h-screen flex-col gap-6 bg-slate-950 px-8 py-16 text-white"
    >
      <header>
        <h1 className="text-kiosk-lg font-bold">부스 지도</h1>
        <p className="mt-1 text-kiosk text-slate-300">
          구역을 눌러 위치를 확인하세요(정밀 실내 내비게이션은 제공하지 않습니다)
        </p>
      </header>

      <div
        data-testid="map-placeholder"
        className="grid flex-1 grid-cols-2 gap-4 rounded-2xl border border-dashed border-slate-700 p-6"
      >
        {zones.map((zone) => (
          <div
            key={zone}
            className="flex min-h-touch items-center justify-center rounded-xl bg-slate-800 text-kiosk font-semibold"
          >
            {zone}
          </div>
        ))}
      </div>

      <Link
        href="/results"
        className="min-h-touch rounded-2xl bg-slate-800 px-6 py-4 text-center text-kiosk font-semibold"
      >
        결과 목록으로 돌아가기
      </Link>
    </main>
  );
}
