"use client";

/**
 * 실내 동선 평면도 - 실제 부스 map_x/map_y와 경로 항목 순서로 그린 SVG 도면.
 *
 * `apps/user-web/components/BoothMatchSimulation.tsx`의 시각 스타일(퍼센트 좌표계
 * viewBox·점선 폴리라인)을 참고하되, DEMO_HALL 상수가 아니라 실제 데이터(`resolveFloorPlanStops`
 * 경유 `getBooth`)로 채운다.
 *
 * 정직성 메모: 벽·통로 그래프 데이터가 없으므로 이 도면은 부스 좌표를 잇는 개략적 평면도이지,
 * 정밀한 턴바이턴 실내 내비게이션이 아니다 - 화면 문구로 항상 이 사실을 밝힌다.
 */

import { useEffect, useState } from "react";

import { resolveFloorPlanStops } from "./api";
import type { ResolvedStop, RouteFloorPlanProps } from "./types";

type LoadState = "loading" | "ready" | "error";

const VIEWBOX_SIZE = 100;
const PADDING = 14;

function layoutPoints(stops: ResolvedStop[]): Map<number, FloorPlanPointXY> {
  const layout = new Map<number, FloorPlanPointXY>();
  if (stops.length === 0) return layout;

  const xs = stops.map((stop) => stop.point.x);
  const ys = stops.map((stop) => stop.point.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  // 모든 점이 한 줄/한 점에 몰려 있으면(span 0) 가운데로 모으고 나눗셈으로 NaN이 나지
  // 않도록 최소 1을 쓴다.
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  const usable = VIEWBOX_SIZE - PADDING * 2;

  for (const stop of stops) {
    layout.set(stop.item.sequence, {
      x: PADDING + ((stop.point.x - minX) / spanX) * usable,
      y: PADDING + ((stop.point.y - minY) / spanY) * usable,
    });
  }
  return layout;
}

interface FloorPlanPointXY {
  x: number;
  y: number;
}

export default function RouteFloorPlan({ items }: RouteFloorPlanProps) {
  const [state, setState] = useState<LoadState>("loading");
  const [resolved, setResolved] = useState<ResolvedStop[]>([]);
  const [unresolvedCount, setUnresolvedCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    if (items.length === 0) {
      setResolved([]);
      setUnresolvedCount(0);
      setState("ready");
      return () => {
        cancelled = true;
      };
    }

    setState("loading");
    resolveFloorPlanStops(items)
      .then((result) => {
        if (cancelled) return;
        setResolved(result.resolved);
        setUnresolvedCount(result.unresolved.length);
        setState("ready");
      })
      .catch(() => {
        if (cancelled) return;
        setState("error");
      });

    return () => {
      cancelled = true;
    };
  }, [items]);

  if (state === "loading") {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex h-56 items-center justify-center border text-sm"
        style={{ borderColor: "var(--color-border)", color: "var(--color-text-muted)" }}
      >
        평면도를 준비하고 있어요...
      </div>
    );
  }

  if (state === "error") {
    return (
      <div
        role="alert"
        className="border p-4 text-sm"
        style={{ borderColor: "var(--color-danger)", color: "var(--color-danger)" }}
      >
        평면도를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.
      </div>
    );
  }

  if (resolved.length === 0) {
    return (
      <div
        className="border p-4 text-sm"
        style={{ borderColor: "var(--color-border)", color: "var(--color-text-muted)" }}
      >
        이 동선에는 지도에 표시할 수 있는 부스 위치 정보가 아직 없어요.
      </div>
    );
  }

  const orderedStops = [...resolved].sort((a, b) => a.item.sequence - b.item.sequence);
  const layout = layoutPoints(orderedStops);
  const points = orderedStops
    .map((stop) => layout.get(stop.item.sequence))
    .filter((point): point is FloorPlanPointXY => Boolean(point))
    .map((point) => `${point.x},${point.y}`)
    .join(" ");

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
        부스 좌표를 기준으로 그린 개략적인 평면도입니다. 벽·통로를 반영한 정밀한 실내
        내비게이션이 아니니 참고용으로만 확인해 주세요.
      </p>

      <div
        role="img"
        aria-label={`추천 방문 순서 평면도: ${orderedStops
          .map((stop, index) => `${index + 1}번 ${stop.boothNumber}`)
          .join(", ")}`}
        className="relative overflow-hidden border"
        style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
      >
        <svg
          viewBox={`0 0 ${VIEWBOX_SIZE} ${VIEWBOX_SIZE}`}
          preserveAspectRatio="xMidYMid meet"
          className="h-64 w-full"
          aria-hidden="true"
        >
          <polyline
            points={points}
            fill="none"
            stroke="var(--color-brand)"
            strokeWidth="1.2"
            strokeDasharray="2.4 1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
          {orderedStops.map((stop, index) => {
            const point = layout.get(stop.item.sequence);
            if (!point) return null;
            return (
              <g key={stop.item.sequence}>
                <circle
                  cx={point.x}
                  cy={point.y}
                  r="3.4"
                  fill="var(--color-brand)"
                  stroke="var(--color-surface)"
                  strokeWidth="0.6"
                />
                <text
                  x={point.x}
                  y={point.y + 1.15}
                  textAnchor="middle"
                  fontSize="3.4"
                  fontWeight="700"
                  fill="var(--color-brand-contrast)"
                >
                  {index + 1}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <ol className="flex flex-col gap-1 text-xs" style={{ color: "var(--color-text-muted)" }}>
        {orderedStops.map((stop, index) => (
          <li key={stop.item.sequence}>
            {index + 1}. {stop.boothNumber}
            {stop.zoneName ? ` · ${stop.zoneName}` : ""}
          </li>
        ))}
      </ol>

      {unresolvedCount > 0 ? (
        <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
          {unresolvedCount}개 방문지는 위치 정보가 없어 지도에 표시하지 못했어요.
        </p>
      ) : null}
    </div>
  );
}
