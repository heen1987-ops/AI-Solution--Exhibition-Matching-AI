"use client";

/**
 * U-13 AI 추천 방문 동선 (`/route`).
 *
 * 추천 Snapshot은 이미 사용자의 관심·방문 목적을 반영한 결과다. 따라서 이 화면은
 * 내부 객체 ID를 다시 입력받지 않고, 승인된 추천 부스를 경로 후보로 자동 구성한다.
 * 사용자는 제안된 순서를 확인하고 필요할 때만 제외·순서·이동 조건을 조정한다.
 */

import Link from "next/link";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import {
  ApiClientError,
  createRoute,
  generateClientId,
  getBooth,
  getProduct,
  getRecommendations,
  recalculateRoute,
} from "@/lib/api-client";
import { enqueueTask, useIsOnline, useOfflineFlush } from "@/lib/offline-queue";
import type {
  RecommendationItem,
  RouteConstraints,
  RouteCreateRequest,
  RouteItemView,
  RouteResponse,
  RouteTargetInput,
} from "@/lib/types";

import CheckpointScanButton from "@/features/indoor-route/CheckpointScanButton";
import RouteFloorPlan from "@/features/indoor-route/RouteFloorPlan";

const QUEUE_KIND = "ROUTE_CREATE";
const LAST_ZONE_KEY = "backju.last_zone.v1";
const DRAFT_TARGETS_KEY = "backju.route_draft_targets.v2";
const DEFAULT_START_ZONE = "입구";
const MAX_ROUTE_TARGETS = 5;
const ZONE_PRESETS = ["입구", "A구역", "B구역", "C구역", "야외무대"];

type DraftTarget = RouteTargetInput & { clientId: string; label: string };
type DraftState = "loading" | "ready" | "empty" | "error";

const ROUTE_ITEM_STATUS_LABEL: Record<string, string> = {
  PENDING: "대기",
  ARRIVED: "도착",
  SKIPPED: "건너뜀",
  COMPLETED: "완료",
};

const ROUTE_STATUS_LABEL: Record<string, string> = {
  ACTIVE: "진행 중",
  COMPLETED: "완료",
  CANCELLED: "취소됨",
};

interface LastZone {
  zone: string;
  observedAt: string;
}

function readLastZone(): LastZone | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(LAST_ZONE_KEY);
    return raw ? (JSON.parse(raw) as LastZone) : null;
  } catch {
    return null;
  }
}

function writeLastZone(zone: string): LastZone {
  const entry: LastZone = { zone, observedAt: new Date().toISOString() };
  try {
    window.localStorage.setItem(LAST_ZONE_KEY, JSON.stringify(entry));
  } catch {
    // 브라우저 저장 실패는 경로 생성 자체를 막지 않는다.
  }
  return entry;
}

function readDraftTargets(): DraftTarget[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(DRAFT_TARGETS_KEY);
    return raw ? (JSON.parse(raw) as DraftTarget[]) : [];
  } catch {
    return [];
  }
}

function writeDraftTargets(targets: DraftTarget[]): void {
  try {
    window.localStorage.setItem(DRAFT_TARGETS_KEY, JSON.stringify(targets));
  } catch {
    // 로컬 초안 저장은 편의 기능이다.
  }
}

function formatTime(iso: string | null): string {
  if (!iso) return "시간 미정";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

function formatSnapshotTime(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString("ko-KR", {
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function normalizePriorities(targets: DraftTarget[]): DraftTarget[] {
  return targets.map((target, index) => ({ ...target, priority: index + 1 }));
}

async function resolveRecommendationTarget(item: RecommendationItem): Promise<DraftTarget | null> {
  if (item.object_type === "BOOTH") {
    try {
      const booth = await getBooth(item.object_id, {
        matchResultId: item.match_result_id ?? undefined,
      });
      return {
        clientId: generateClientId(),
        object_type: "BOOTH",
        object_id: booth.booth_id,
        label: `${booth.exhibitor.name} · ${booth.booth_number}`,
        priority: item.rank,
        expected_duration_minutes: 15,
      };
    } catch {
      return {
        clientId: generateClientId(),
        object_type: "BOOTH",
        object_id: item.object_id,
        label: `추천 부스 ${item.rank}`,
        priority: item.rank,
        expected_duration_minutes: 15,
      };
    }
  }

  if (item.object_type === "PRODUCT") {
    try {
      const product = await getProduct(item.object_id);
      if (!product.booth_id) return null;
      return {
        clientId: generateClientId(),
        object_type: "BOOTH",
        object_id: product.booth_id,
        label: `${product.exhibitor.name} · ${product.product_name}`,
        priority: item.rank,
        expected_duration_minutes: 15,
      };
    } catch {
      return null;
    }
  }

  return null;
}

async function buildRecommendedTargets(items: RecommendationItem[]): Promise<DraftTarget[]> {
  const routeCandidates = items
    .filter((item) => item.object_type === "BOOTH" || item.object_type === "PRODUCT")
    .sort((a, b) => {
      const typeOrder = Number(a.object_type !== "BOOTH") - Number(b.object_type !== "BOOTH");
      return typeOrder || a.rank - b.rank;
    })
    .slice(0, MAX_ROUTE_TARGETS * 2);

  const resolved = await Promise.all(routeCandidates.map(resolveRecommendationTarget));
  const unique = new Map<string, DraftTarget>();
  for (const target of resolved) {
    if (!target) continue;
    const key = `${target.object_type}:${target.object_id}`;
    if (!unique.has(key)) unique.set(key, target);
    if (unique.size >= MAX_ROUTE_TARGETS) break;
  }
  return normalizePriorities([...unique.values()]);
}

export default function RoutePage() {
  return (
    <Suspense fallback={<RoutePageFallback />}>
      <RoutePageContent />
    </Suspense>
  );
}

function RoutePageFallback() {
  return (
    <div className="mx-auto max-w-screen-content px-4 py-6">
      <p style={{ color: "var(--color-text-muted)" }}>추천 동선을 준비하고 있어요...</p>
    </div>
  );
}

function RoutePageContent() {
  const searchParams = useSearchParams();
  const isOnline = useIsOnline();
  const source = searchParams?.get("source");
  const addType = searchParams?.get("addType");
  const addId = searchParams?.get("addId");
  const addLabel = searchParams?.get("addLabel");

  const [lastZone, setLastZone] = useState<LastZone | null>(null);
  const [currentZone, setCurrentZone] = useState(DEFAULT_START_ZONE);
  const [targets, setTargets] = useState<DraftTarget[]>([]);
  const [draftState, setDraftState] = useState<DraftState>("loading");
  const [snapshotGeneratedAt, setSnapshotGeneratedAt] = useState<string | null>(null);
  const [availableMinutes, setAvailableMinutes] = useState<number | "">(90);
  const [avoidCongestion, setAvoidCongestion] = useState(true);
  const [minimizeWalking, setMinimizeWalking] = useState(false);
  const [accessibleRoute, setAccessibleRoute] = useState(false);

  const [route, setRoute] = useState<RouteResponse | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRecalculating, setIsRecalculating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function initializeDraft() {
      const storedZone = readLastZone();
      if (!cancelled) {
        setLastZone(storedZone);
        setCurrentZone(storedZone?.zone ?? DEFAULT_START_ZONE);
        setDraftState("loading");
      }

      const explicitTarget: DraftTarget | null =
        addType && addId
          ? {
              clientId: generateClientId(),
              object_type: addType as RouteTargetInput["object_type"],
              object_id: addId,
              label: addLabel ?? "추가한 방문지",
              priority: 1,
              expected_duration_minutes: 15,
            }
          : null;

      const storedTargets = source === "recommendations" ? [] : readDraftTargets();
      try {
        const recommendations = await getRecommendations();
        const recommendedTargets = await buildRecommendedTargets(recommendations.items);
        if (cancelled) return;

        const merged = normalizePriorities(
          [explicitTarget, ...storedTargets, ...recommendedTargets]
            .filter((target): target is DraftTarget => Boolean(target))
            .filter(
              (target, index, all) =>
                all.findIndex(
                  (candidate) =>
                    candidate.object_type === target.object_type && candidate.object_id === target.object_id,
                ) === index,
            )
            .slice(0, MAX_ROUTE_TARGETS),
        );
        setTargets(merged);
        writeDraftTargets(merged);
        setSnapshotGeneratedAt(recommendations.generated_at);
        setDraftState(merged.length > 0 ? "ready" : "empty");
      } catch (err) {
        if (cancelled) return;
        const fallback = normalizePriorities(
          [explicitTarget, ...storedTargets].filter((target): target is DraftTarget => Boolean(target)),
        );
        setTargets(fallback);
        setDraftState(
          fallback.length > 0
            ? "ready"
            : err instanceof ApiClientError && err.code === "RECOMMENDATION_NOT_READY"
              ? "empty"
              : "error",
        );
      }
    }

    void initializeDraft();
    return () => {
      cancelled = true;
    };
  }, [source, addType, addId, addLabel]);

  const constraints: RouteConstraints = useMemo(
    () => ({
      available_minutes: availableMinutes === "" ? null : availableMinutes,
      avoid_congestion: avoidCongestion,
      minimize_walking: minimizeWalking,
      accessible_route: accessibleRoute,
    }),
    [availableMinutes, avoidCongestion, minimizeWalking, accessibleRoute],
  );

  const buildRequest = (): RouteCreateRequest | null => {
    if (targets.length === 0) {
      setError("추천 업체가 준비된 뒤 방문 동선을 시작할 수 있어요.");
      return null;
    }
    return {
      start_location: { type: "ZONE", id: currentZone },
      targets: targets.map((target) => ({
        object_type: target.object_type,
        object_id: target.object_id,
        priority: target.priority,
        expected_duration_minutes: target.expected_duration_minutes,
      })),
      constraints,
    };
  };

  const { tasks: queuedRouteTasks } = useOfflineFlush<RouteCreateRequest>(
    QUEUE_KIND,
    async (payload, idempotencyKey) => {
      const result = await createRoute(payload, { idempotencyKey });
      setRoute(result);
      setStatusMessage("저장했던 방문 동선 요청이 전송되어 확정되었습니다.");
      return { resultId: result.route_id };
    },
  );

  const pendingRouteTask = queuedRouteTasks.find(
    (task) => task.status === "queued" || task.status === "sending" || task.status === "retryable_error",
  );

  function removeTarget(clientId: string) {
    const next = normalizePriorities(targets.filter((target) => target.clientId !== clientId));
    setTargets(next);
    writeDraftTargets(next);
  }

  function moveTarget(clientId: string, direction: -1 | 1) {
    const index = targets.findIndex((target) => target.clientId === clientId);
    const nextIndex = index + direction;
    if (index === -1 || nextIndex < 0 || nextIndex >= targets.length) return;
    const next = [...targets];
    const [item] = next.splice(index, 1);
    next.splice(nextIndex, 0, item);
    const reordered = normalizePriorities(next);
    setTargets(reordered);
    writeDraftTargets(reordered);
  }

  function selectZone(zone: string) {
    setCurrentZone(zone);
    setLastZone(writeLastZone(zone));
  }

  async function handleStartRoute() {
    if (isSubmitting) return;
    setError(null);
    setStatusMessage(null);
    const request = buildRequest();
    if (!request) return;

    setIsSubmitting(true);
    const idempotencyKey = generateClientId();
    try {
      const result = await createRoute(request, { idempotencyKey });
      setRoute(result);
      setStatusMessage("추천 방문 동선을 시작했습니다.");
    } catch (err) {
      if (err instanceof ApiClientError && (err.code === "NETWORK_ERROR" || err.retryable)) {
        enqueueTask(QUEUE_KIND, request, idempotencyKey);
        setStatusMessage("연결이 불안정해 요청을 저장했습니다. 연결되면 자동으로 다시 보냅니다.");
      } else if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("방문 동선을 시작하지 못했습니다.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleRecalculate() {
    if (!route || isRecalculating) return;
    setIsRecalculating(true);
    setError(null);
    try {
      const result = await recalculateRoute(route.route_id);
      setRoute(result);
      setStatusMessage("현재 위치와 운영 상태를 반영해 동선을 다시 계산했습니다.");
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "동선을 다시 계산하지 못했습니다.");
    } finally {
      setIsRecalculating(false);
    }
  }

  function handleCheckpointScanned(updatedRoute: RouteResponse | null) {
    if (updatedRoute) {
      setRoute(updatedRoute);
      setStatusMessage("현재 위치를 확인해 남은 동선을 다시 계산했습니다.");
    }
  }

  const snapshotTime = formatSnapshotTime(snapshotGeneratedAt);

  return (
    <div className="mx-auto flex max-w-screen-content flex-col gap-6 px-4 py-6 md:gap-8 md:py-8">
      <header className="backju-section-title">
        <p className="backju-eyebrow" style={{ color: "var(--color-brand)" }}>
          MY RECOMMENDED ROUTE
        </p>
        <h1 className="mt-1 text-2xl font-extrabold">AI 추천 방문 동선</h1>
        <p className="mt-2 max-w-2xl text-sm" style={{ color: "var(--color-text-muted)" }}>
          나의 추천 결과에서 방문 후보를 먼저 준비했습니다. 아래 동선을 확인한 뒤 바로 시작하거나,
          필요한 항목만 가볍게 조정하세요.
        </p>
      </header>

      {!isOnline || pendingRouteTask ? (
        <div
          role="status"
          aria-live="polite"
          className="border-l-4 px-4 py-3 text-sm"
          style={{
            borderColor: "var(--color-brand)",
            backgroundColor: "var(--color-brand-soft)",
          }}
        >
          {!isOnline
            ? "오프라인 상태입니다. 현재 동선은 볼 수 있으며 시작 요청은 연결 후 자동 전송됩니다."
            : pendingRouteTask?.status === "sending"
              ? "저장된 동선 요청을 다시 보내고 있습니다."
              : "네트워크 연결을 기다리는 동선 요청이 있습니다."}
        </div>
      ) : null}

      <section
        aria-labelledby="route-summary-heading"
        className="backju-panel grid gap-4 border p-5 md:grid-cols-[1fr_auto] md:items-center md:p-6"
        style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
      >
        <div>
          <h2 id="route-summary-heading" className="text-lg font-bold">
            오늘의 추천 동선
          </h2>
          <p className="mt-1 text-sm" style={{ color: "var(--color-text-muted)" }}>
            {draftState === "loading"
              ? "추천 업체를 경로 후보로 정리하고 있어요."
              : targets.length > 0
                ? `${currentZone}에서 출발 · 추천 부스 ${targets.length}곳 · 약 ${availableMinutes || "?"}분`
                : "추천 결과가 준비되면 방문 동선을 자동으로 보여드려요."}
          </p>
          {snapshotTime ? (
            <p className="mt-1 text-xs" style={{ color: "var(--color-text-muted)" }}>
              {snapshotTime} 추천 결과 기준
            </p>
          ) : null}
        </div>
        {targets.length > 0 ? (
          <button
            type="button"
            onClick={handleStartRoute}
            disabled={isSubmitting}
            className="tap-target rounded-full px-6 py-3 text-sm font-bold disabled:opacity-60"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
          >
            {isSubmitting ? "동선 계산 중..." : route ? "이 동선 다시 시작" : "이 동선으로 시작"}
          </button>
        ) : null}
      </section>

      <section aria-labelledby="targets-heading" className="flex flex-col gap-3">
        <div className="flex items-end justify-between gap-3">
          <div>
            <h2 id="targets-heading" className="backju-section-title text-lg font-bold">
              추천 방문 순서
            </h2>
            <p className="mt-1 text-sm" style={{ color: "var(--color-text-muted)" }}>
              그대로 이용해도 되고, 원하지 않는 곳만 빼거나 순서를 바꿀 수 있어요.
            </p>
          </div>
          <span className="shrink-0 text-sm font-semibold" style={{ color: "var(--color-brand)" }}>
            {targets.length}곳
          </span>
        </div>

        {draftState === "loading" ? (
          <div className="space-y-2" aria-label="추천 동선 불러오는 중">
            {[0, 1, 2].map((item) => (
              <div
                key={item}
                className="h-20 animate-pulse border"
                style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-brand-soft)" }}
              />
            ))}
          </div>
        ) : targets.length > 0 ? (
          <ol className="grid gap-3 md:grid-cols-2">
            {targets.map((target, index) => {
              const routeItem: RouteItemView | undefined = route?.items[index];
              return (
                <li
                  key={target.clientId}
                  className="recommendation-card border p-4"
                  style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
                >
                  <div className="flex items-start gap-3">
                    <span
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-extrabold"
                      style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
                      aria-label={`${index + 1}번째 방문`}
                    >
                      {index + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="font-bold">{target.label}</p>
                      <p className="mt-0.5 text-xs" style={{ color: "var(--color-text-muted)" }}>
                        추천 체류 약 {target.expected_duration_minutes ?? 15}분
                        {routeItem
                          ? ` · 도착 ${formatTime(routeItem.expected_arrival_at)} · ${
                              ROUTE_ITEM_STATUS_LABEL[routeItem.status] ?? routeItem.status
                            }`
                          : ""}
                      </p>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap justify-end gap-1.5">
                    <button
                      type="button"
                      onClick={() => moveTarget(target.clientId, -1)}
                      disabled={index === 0}
                      className="tap-target border px-3 text-xs font-semibold disabled:opacity-35"
                      style={{ borderColor: "var(--color-border)" }}
                      aria-label={`${target.label} 순서를 앞으로 이동`}
                    >
                      앞 순서
                    </button>
                    <button
                      type="button"
                      onClick={() => moveTarget(target.clientId, 1)}
                      disabled={index === targets.length - 1}
                      className="tap-target border px-3 text-xs font-semibold disabled:opacity-35"
                      style={{ borderColor: "var(--color-border)" }}
                      aria-label={`${target.label} 순서를 뒤로 이동`}
                    >
                      뒤 순서
                    </button>
                    <button
                      type="button"
                      onClick={() => removeTarget(target.clientId)}
                      className="tap-target px-3 text-xs font-semibold"
                      style={{ color: "var(--color-text-muted)" }}
                      aria-label={`${target.label} 방문 동선에서 제외`}
                    >
                      제외
                    </button>
                  </div>
                </li>
              );
            })}
          </ol>
        ) : (
          <div className="backju-panel border p-5" style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}>
            <p className="font-semibold">
              {draftState === "error" ? "추천 동선을 아직 불러오지 못했어요." : "추천 방문 후보가 아직 없어요."}
            </p>
            <p className="mt-1 text-sm" style={{ color: "var(--color-text-muted)" }}>
              {draftState === "error"
                ? "추천 업체 화면을 확인하거나 잠시 뒤 다시 들어오면 동선을 자동으로 준비합니다."
                : "내부 ID를 직접 입력할 필요는 없습니다. 추천 업체가 준비되면 이 화면에 자동으로 반영됩니다."}
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Link
                href="/recommendations"
                className="tap-target rounded-full px-5 text-sm font-bold"
                style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
              >
                추천 업체 확인
              </Link>
              <Link
                href="/explore"
                className="tap-target border px-4 text-sm font-semibold"
                style={{ borderColor: "var(--color-border)" }}
              >
                업체 직접 찾기
              </Link>
            </div>
          </div>
        )}
      </section>

      {targets.length > 0 ? (
        <details className="border-y py-4" style={{ borderColor: "var(--color-border)" }}>
        <summary className="tap-target cursor-pointer justify-start text-sm font-bold">
          이동 조건 조정
        </summary>
        <div className="mt-4 grid gap-5 md:grid-cols-2">
          <fieldset className="space-y-2">
            <legend className="text-sm font-semibold">출발 위치</legend>
            {lastZone ? (
              <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
                최근 확인 위치를 자동 적용했습니다.
              </p>
            ) : null}
            <div className="flex flex-wrap gap-2">
              {ZONE_PRESETS.map((zone) => (
                <button
                  key={zone}
                  type="button"
                  onClick={() => selectZone(zone)}
                  className="tap-target rounded-full border px-4 text-sm"
                  aria-pressed={currentZone === zone}
                  style={{
                    borderColor: currentZone === zone ? "var(--color-brand)" : "var(--color-border)",
                    backgroundColor: currentZone === zone ? "var(--color-brand)" : "var(--color-surface)",
                    color: currentZone === zone ? "var(--color-brand-contrast)" : "var(--color-text)",
                  }}
                >
                  {zone}
                </button>
              ))}
            </div>
          </fieldset>

          <div className="space-y-3">
            <label className="flex items-center justify-between gap-4 text-sm">
              <span>이용 가능 시간</span>
              <span className="flex items-center gap-2">
                <input
                  type="number"
                  min={15}
                  step={15}
                  value={availableMinutes}
                  onChange={(event) =>
                    setAvailableMinutes(event.target.value === "" ? "" : Number(event.target.value))
                  }
                  className="w-24 border px-3 py-2 text-right"
                  style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
                  aria-label="이용 가능 시간(분)"
                />
                분
              </span>
            </label>
            <label className="tap-target w-full cursor-pointer justify-start gap-3 text-sm">
              <input
                type="checkbox"
                checked={avoidCongestion}
                onChange={(event) => setAvoidCongestion(event.target.checked)}
                className="h-5 w-5"
              />
              혼잡한 부스는 피하기
            </label>
            <label className="tap-target w-full cursor-pointer justify-start gap-3 text-sm">
              <input
                type="checkbox"
                checked={minimizeWalking}
                onChange={(event) => setMinimizeWalking(event.target.checked)}
                className="h-5 w-5"
              />
              이동거리 줄이기
            </label>
            <label className="tap-target w-full cursor-pointer justify-start gap-3 text-sm">
              <input
                type="checkbox"
                checked={accessibleRoute}
                onChange={(event) => setAccessibleRoute(event.target.checked)}
                className="h-5 w-5"
              />
              휠체어·유모차 이동이 편한 길
            </label>
          </div>
        </div>
        </details>
      ) : null}

      {route ? (
        <section
          aria-live="polite"
          className="backju-panel flex flex-col gap-4 border p-5"
          style={{ borderColor: "var(--color-mint)", backgroundColor: "var(--color-surface)" }}
        >
          <div>
            <p className="font-bold">
              약 {route.total_minutes ?? "?"}분 · 이동 {route.walking_minutes ?? "?"}분
            </p>
            <p className="mt-1 text-xs" style={{ color: "var(--color-text-muted)" }}>
              경로 상태: {ROUTE_STATUS_LABEL[route.status] ?? route.status}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={handleRecalculate}
                disabled={isRecalculating}
                className="tap-target border px-4 text-sm font-semibold disabled:opacity-60"
                style={{ borderColor: "var(--color-border)" }}
              >
                {isRecalculating ? "다시 계산 중..." : "현재 상태로 다시 계산"}
              </button>
              <CheckpointScanButton onScanned={handleCheckpointScanned} />
            </div>
          </div>

          <RouteFloorPlan items={route.items} />
        </section>
      ) : null}

      {error ? (
        <p role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
          {error}
        </p>
      ) : null}
      {statusMessage ? (
        <p role="status" aria-live="polite" className="text-sm" style={{ color: "var(--color-success)" }}>
          {statusMessage}
        </p>
      ) : null}
    </div>
  );
}
