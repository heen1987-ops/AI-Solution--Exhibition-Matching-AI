"use client";

import { useMemo, useState } from "react";

import {
  buildDemoRoute,
  DEMO_CATEGORIES,
  DEMO_EXHIBITORS,
  DEMO_HALL,
  DEMO_VISITOR_PROFILE,
  orderDemoRouteByAisle,
  rankDemoExhibitors,
  selectDemoRecommendations,
  type DemoCategory,
  type RankedDemoExhibitor,
} from "@/lib/booth-map-simulation";

const CATEGORY_STYLE: Record<DemoCategory, string> = {
  우리술: "border-[#bd6b76] bg-[#f6d8dc] text-[#5a2d33]",
  기타주류: "border-[#b79762] bg-[#f3e1bc] text-[#59431f]",
  연관제품: "border-[#93a7bd] bg-[#dfe8f2] text-[#30455a]",
  기술: "border-[#6e9b88] bg-[#d6e9df] text-[#294b3d]",
  가맹: "border-[#9a84b3] bg-[#e9def3] text-[#49345f]",
  지역문화: "border-[#d28c62] bg-[#f5ddcd] text-[#633a23]",
};

const SPECIAL_ZONES = [
  { label: "백주 사랑방", detail: "바이어 상담", left: "3%", width: "21%", tone: "bg-[#dfe8f2] border-[#93a7bd]" },
  { label: "달구벌 술곳간", detail: "지역술 테이스팅", left: "27%", width: "22%", tone: "bg-[#f3e1bc] border-[#b79762]" },
  { label: "달구벌 주막", detail: "휴게·지역음식", left: "52%", width: "21%", tone: "bg-[#f5ddcd] border-[#d28c62]" },
  { label: "초이스, 대구!!", detail: "현장 투표", left: "76%", width: "21%", tone: "bg-[#e9def3] border-[#9a84b3]" },
] as const;

function routePointString(route: readonly RankedDemoExhibitor[]): string {
  const points: Array<{ x: number; y: number }> = [DEMO_HALL.entrance];
  let previous: RankedDemoExhibitor | null = null;

  for (const stop of route) {
    const approachY = stop.y + 5.2;
    if (previous) {
      const previousAisleY = previous.y + 5.2;
      points.push({ x: previous.x, y: previousAisleY });
      if (previous.y === stop.y) {
        points.push({ x: stop.x, y: approachY });
      } else {
        const turnX = previous.x >= DEMO_HALL.entrance.x ? 96 : 4;
        points.push({ x: turnX, y: previousAisleY });
        points.push({ x: turnX, y: approachY });
        points.push({ x: stop.x, y: approachY });
      }
    } else {
      points.push({ x: DEMO_HALL.entrance.x, y: approachY });
      points.push({ x: stop.x, y: approachY });
    }
    points.push({ x: stop.x, y: stop.y });
    previous = stop;
  }

  return points.map((point) => `${point.x},${point.y}`).join(" ");
}

export default function BoothMatchSimulation() {
  const [interests, setInterests] = useState<DemoCategory[]>(DEMO_VISITOR_PROFILE.interests);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const ranked = useMemo(() => rankDemoExhibitors(interests), [interests]);
  const recommendations = useMemo(() => selectDemoRecommendations(ranked, interests, 10), [interests, ranked]);
  const numberedStops = useMemo(() => buildDemoRoute(recommendations, 6), [recommendations]);
  const visitRoute = useMemo(() => orderDemoRouteByAisle(numberedStops), [numberedStops]);
  const recommendationIds = useMemo(() => new Set(recommendations.map((item) => item.id)), [recommendations]);
  const routeRanks = useMemo(() => new Map(numberedStops.map((item, index) => [item.id, index + 1])), [numberedStops]);
  const selected = ranked.find((item) => item.id === selectedId) ?? visitRoute[0] ?? recommendations[0];

  const toggleInterest = (category: DemoCategory) => {
    setInterests((current) => {
      if (current.includes(category)) {
        return current.length === 1 ? current : current.filter((item) => item !== category);
      }
      return [...current, category];
    });
    setSelectedId(null);
  };

  return (
    <section aria-labelledby="booth-simulation-heading" className="overflow-hidden border border-[var(--color-border)] bg-white backju-panel">
      <div className="border-b border-[var(--color-border)] p-5 md:p-7">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="backju-eyebrow text-brand-600">PERSONAL BOOTH ROUTE</p>
            <h2 id="booth-simulation-heading" className="mt-2 text-2xl font-black tracking-[-0.03em] text-[#302f2c] md:text-3xl">
              3홀 추천 부스 시뮬레이션
            </h2>
          </div>
          <span className="rounded-full bg-[#f7d8da] px-3 py-1 text-xs font-black text-[#7d2931]">
            가상업체·추론 배치
          </span>
        </div>

        <p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--color-text-muted)]">
          3홀 4,410㎡와 행사 홈페이지의 전시품목·부대행사를 바탕으로 구성한 검증용 배치입니다. 50개 가상업체 중 관심사에 맞는 10곳을 고르고, 입구에서 가까운 순서로 6곳의 추천 경로를 표시합니다.
        </p>

        <div className="mt-5">
          <strong className="text-sm text-[#3f3b33]">{DEMO_VISITOR_PROFILE.displayName} 님의 테스트 관심사</strong>
          <div className="mt-2 flex flex-wrap gap-2" aria-label="매칭 관심사 선택">
            {DEMO_CATEGORIES.map((category) => {
              const active = interests.includes(category);
              return (
                <button
                  key={category}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleInterest(category)}
                  className={`tap-target rounded-full border px-4 text-sm font-extrabold transition ${
                    active ? "border-brand-600 bg-brand-600 text-white" : "border-[var(--color-border)] bg-white text-[#5b574f] hover:border-brand-300"
                  }`}
                >
                  {category}
                </button>
              );
            })}
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <div className="border-l-4 border-[#d6b168] bg-[#faf7f0] px-4 py-3">
            <strong className="block text-xl text-[#3f3b33]">{DEMO_EXHIBITORS.length}곳</strong>
            <span className="text-xs text-[var(--color-text-muted)]">가상 참가업체</span>
          </div>
          <div className="border-l-4 border-[#be6f79] bg-[#fcf3f4] px-4 py-3">
            <strong className="block text-xl text-[#3f3b33]">{recommendations.length}곳</strong>
            <span className="text-xs text-[var(--color-text-muted)]">관심사 우선 추천</span>
          </div>
          <div className="border-l-4 border-[#6e9b88] bg-[#f1f7f4] px-4 py-3">
            <strong className="block text-xl text-[#3f3b33]">{visitRoute.length}곳</strong>
            <span className="text-xs text-[var(--color-text-muted)]">현장 추천 경로</span>
          </div>
        </div>
      </div>

      <div className="grid gap-0 xl:grid-cols-[minmax(0,1.65fr)_minmax(300px,0.75fr)]">
        <div className="overflow-x-auto bg-[#f4f0e8] p-3 md:p-6" role="region" aria-label="가상 3홀 부스 배치도" tabIndex={0}>
          <div className="relative mx-auto h-[610px] min-w-[900px] max-w-[1100px] overflow-hidden border-2 border-[#8f8a80] bg-[#fffdf8] shadow-[0_14px_34px_rgba(72,58,34,0.1)]">
            <div className="absolute inset-x-0 top-0 h-[17%] border-b-8 border-[#f4f0e8] bg-[#faf7f0]">
              {SPECIAL_ZONES.map((zone) => (
                <div
                  key={zone.label}
                  className={`absolute top-[14%] flex h-[67%] flex-col items-center justify-center border text-center ${zone.tone}`}
                  style={{ left: zone.left, width: zone.width }}
                >
                  <strong className="text-xs">{zone.label}</strong>
                  <span className="mt-1 text-[0.62rem] opacity-75">{zone.detail}</span>
                </div>
              ))}
            </div>

            <svg className="pointer-events-none absolute inset-0 z-10 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              <polyline
                points={routePointString(visitRoute)}
                fill="none"
                stroke="#a83943"
                strokeWidth="0.75"
                strokeDasharray="1.3 1.1"
                strokeLinecap="round"
                strokeLinejoin="round"
                vectorEffect="non-scaling-stroke"
              />
            </svg>

            {ranked.map((exhibitor) => {
              const routeRank = routeRanks.get(exhibitor.id);
              const recommended = recommendationIds.has(exhibitor.id);
              const isSelected = selected?.id === exhibitor.id;
              return (
                <button
                  key={exhibitor.id}
                  type="button"
                  onClick={() => setSelectedId(exhibitor.id)}
                  aria-label={`${exhibitor.boothNumber} ${exhibitor.name} ${exhibitor.product}${recommended ? " 추천 업체" : ""}`}
                  className={`absolute z-20 flex items-center justify-center border px-1 text-center text-[0.62rem] font-black leading-tight transition hover:z-30 hover:scale-110 ${CATEGORY_STYLE[exhibitor.category]} ${
                    recommended ? "ring-2 ring-[#a83943] ring-offset-1" : ""
                  } ${isSelected ? "z-30 scale-110 shadow-lg outline outline-2 outline-[#302f2c]" : ""}`}
                  style={{
                    left: `calc(${exhibitor.x}% - 3.65%)`,
                    top: `calc(${exhibitor.y}% - 3.2%)`,
                    width: "7.3%",
                    height: "6.4%",
                  }}
                >
                  {exhibitor.boothNumber}
                  {routeRank ? (
                    <span className="absolute -right-2 -top-2 flex h-5 w-5 items-center justify-center rounded-full bg-[#a83943] text-[0.62rem] text-white shadow">
                      {routeRank}
                    </span>
                  ) : null}
                </button>
              );
            })}

            <div className="absolute bottom-[1.5%] left-1/2 z-20 -translate-x-1/2 border-t-4 border-brand-600 px-16 pt-1 text-center text-xs font-black tracking-[0.18em] text-brand-700">
              ↑ 입구
            </div>
          </div>
        </div>

        <aside className="border-t border-[var(--color-border)] bg-white p-5 xl:border-l xl:border-t-0 xl:p-6" aria-label="추천 경로와 선택 부스 정보">
          <p className="backju-eyebrow text-brand-600">RECOMMENDED ROUTE</p>
          <h3 className="mt-2 text-xl font-black text-[#302f2c]">통로 기준 방문 순서</h3>
          <p className="mt-2 text-sm font-extrabold text-[#a83943]">
            {visitRoute.map((item) => routeRanks.get(item.id)).join(" → ")}
          </p>
          <ol className="mt-4 space-y-2">
            {visitRoute.map((exhibitor, index) => {
              const markerNumber = routeRanks.get(exhibitor.id);
              return (
              <li key={exhibitor.id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(exhibitor.id)}
                  className={`w-full border px-3 py-3 text-left transition ${selected?.id === exhibitor.id ? "border-[#a83943] bg-[#fcf3f4]" : "border-[var(--color-border)] hover:border-brand-300"}`}
                >
                  <span className="flex items-start gap-3">
                    <span className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-[#a83943] text-xs font-black text-white">{markerNumber}</span>
                    <span className="min-w-0">
                      <strong className="block truncate text-sm text-[#3f3b33]">방문 {index + 1} · {exhibitor.boothNumber} · {exhibitor.name}</strong>
                      <small className="mt-1 block text-xs leading-5 text-[var(--color-text-muted)]">{exhibitor.reason}</small>
                    </span>
                  </span>
                </button>
              </li>
              );
            })}
          </ol>

          {selected ? (
            <div className="mt-5 border-l-4 border-[#d6b168] bg-[#faf7f0] p-4" aria-live="polite">
              <span className="text-xs font-black text-brand-700">선택 부스 · {selected.category}</span>
              <strong className="mt-1 block text-base text-[#302f2c]">{selected.boothNumber} · {selected.name}</strong>
              <span className="mt-1 block text-sm text-[#5b574f]">대표 품목: {selected.product}</span>
              <p className="mt-2 text-xs leading-5 text-[var(--color-text-muted)]">{selected.reason}</p>
            </div>
          ) : null}

          <div className="mt-5 flex flex-wrap gap-x-3 gap-y-2" aria-label="부스 범례">
            {DEMO_CATEGORIES.map((category) => (
              <span key={category} className={`border px-2 py-1 text-[0.68rem] font-bold ${CATEGORY_STYLE[category]}`}>{category}</span>
            ))}
          </div>
        </aside>
      </div>

      <div className="border-t border-[var(--color-border)] bg-[#faf7f0] px-5 py-4 text-xs leading-5 text-[var(--color-text-muted)] md:px-7">
        이 도면과 업체명은 기능 검증용 시뮬레이션이며 실제 참가업체·부스배정을 의미하지 않습니다. 공식 배치도와 승인 업체 데이터가 확보되면 같은 화면 구조에 실제 추천 Snapshot을 연결합니다.
        <span className="ml-2 inline-flex flex-wrap gap-2">
          <a href="https://www.backju.kr/sub.php?code=01_0101" target="_blank" rel="noreferrer" className="font-bold text-brand-700 underline underline-offset-2">행사개요</a>
          <a href="https://www.backju.kr/sub.php?code=06_0605" target="_blank" rel="noreferrer" className="font-bold text-brand-700 underline underline-offset-2">부대행사</a>
          <a href="https://www.exco.co.kr/facility/sub01_1.html?snm=36" target="_blank" rel="noreferrer" className="font-bold text-brand-700 underline underline-offset-2">EXCO 3홀</a>
        </span>
      </div>
    </section>
  );
}
