"use client";

/**
 * U-13 지도·추천 경로 (`/route`).
 *
 * 근거 문서
 * ---------
 * - docs/user-ia-wireframes.md 7절 U-13 와이어프레임: 현재 구역 표시(`최근 QR: B구역 ·
 *   14:22`처럼 출처·시각 병기), 방문 순서 목록, "약 55분 · 이동 12분" 요약, `[경로 시작]`
 *   `[순서 변경]` `[혼잡 부스 제외]` 액션, "QR 스캔이 어려운 사용자는 지도에서 현재 구역을
 *   직접 선택할 수 있다".
 * - docs/user-ia-wireframes.md 13.2절: "지도 정보는 목록·텍스트 경로로도 제공" - 이 화면은
 *   지도 라이브러리를 쓰지 않고 처음부터 텍스트 목록만으로 구현한다.
 * - docs/user-ia-wireframes.md 6.4절, 11.4절: 경로 시작 요청도 외부 효과가 있는 POST이므로
 *   네트워크 단절 시 로컬 큐잉·재연결 자동 재전송 대상으로 다룬다.
 * - docs/frontend-backend-ai-interface-spec.md 11.2절: `POST /routes` 요청 바디 형태,
 *   재계산 조건(구역/남은시간 변경, 방문 완료, 상담 상태 변화, 부스 상태 변화 등).
 * - frontend/lib/types.ts `RouteCreateRequest`/`RouteResponse`/`RouteTargetInput` 그대로 사용.
 *
 * 통합 메모: 부스·제품 상세(U-10/U-11)나 추천 목록(U-09)의 "경로 추가" 버튼은 이 화면을
 * `?addType=BOOTH&addId=booth_012&addLabel=A양조장` 형태 쿼리스트링으로 열어 목적지를
 * 자동으로 추가할 수 있다(그 화면들은 이 작업 범위 밖이라 실제 연동은 하지 않았다).
 */

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import { ApiClientError, createRoute, generateClientId, recalculateRoute } from "@/lib/api-client";
import { enqueueTask, useIsOnline, useOfflineFlush } from "@/lib/offline-queue";
import type {
  RouteConstraints,
  RouteCreateRequest,
  RouteItemView,
  RouteResponse,
  RouteTargetInput,
} from "@/lib/types";

const QUEUE_KIND = "ROUTE_CREATE";
const LAST_ZONE_KEY = "backju.last_zone.v1";
const DRAFT_TARGETS_KEY = "backju.route_draft_targets.v1";

const ZONE_PRESETS = ["입구", "A구역", "B구역", "C구역", "야외무대"];

type DraftTarget = RouteTargetInput & { clientId: string; label: string };

const OBJECT_TYPE_LABEL: Record<RouteTargetInput["object_type"], string> = {
  BOOTH: "부스",
  PRODUCT: "제품",
  EXHIBITOR: "업체",
  PROGRAM: "프로그램",
  MEETING: "상담",
};

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
    // 저장 실패는 화면 동작에 영향을 주지 않는다.
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
    // 무시 - 로컬 편의 저장일 뿐이다.
  }
}

function formatTime(iso: string | null): string {
  if (!iso) return "시간 미정";
  try {
    return new Date(iso).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function formatObservedAt(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
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
      <p style={{ color: "var(--color-text-muted)" }}>불러오는 중...</p>
    </div>
  );
}

function RoutePageContent() {
  const searchParams = useSearchParams();
  const isOnline = useIsOnline();

  const [lastZone, setLastZone] = useState<LastZone | null>(null);
  const [currentZone, setCurrentZone] = useState("");
  const [targets, setTargets] = useState<DraftTarget[]>([]);
  const [availableMinutes, setAvailableMinutes] = useState<number | "">("");
  const [avoidCongestion, setAvoidCongestion] = useState(false);
  const [minimizeWalking, setMinimizeWalking] = useState(false);
  const [accessibleRoute, setAccessibleRoute] = useState(false);

  const [route, setRoute] = useState<RouteResponse | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRecalculating, setIsRecalculating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  // 새 목적지 추가 폼 상태.
  const [newType, setNewType] = useState<RouteTargetInput["object_type"]>("BOOTH");
  const [newId, setNewId] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [newDuration, setNewDuration] = useState<number | "">("");

  useEffect(() => {
    setLastZone(readLastZone());
    setTargets(readDraftTargets());
  }, []);

  // 다른 화면에서 ?addType=BOOTH&addId=booth_012&addLabel=A%EC%96%91%EC%A1%B0%EC%9E%A5 로
  // 들어오면 목적지를 한 번 자동 추가한다.
  useEffect(() => {
    const addType = searchParams?.get("addType");
    const addId = searchParams?.get("addId");
    if (!addType || !addId) return;
    const label = searchParams?.get("addLabel") ?? addId;
    setTargets((prev) => {
      if (prev.some((t) => t.object_type === addType && t.object_id === addId)) return prev;
      const next: DraftTarget[] = [
        ...prev,
        {
          clientId: generateClientId(),
          object_type: addType as RouteTargetInput["object_type"],
          object_id: addId,
          label,
          priority: prev.length + 1,
        },
      ];
      writeDraftTargets(next);
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    const zone = currentZone.trim();
    if (!zone) {
      setError("현재 구역을 선택하거나 입력해 주세요.");
      return null;
    }
    if (targets.length === 0) {
      setError("경로에 추가할 목적지를 1개 이상 넣어 주세요.");
      return null;
    }
    return {
      start_location: { type: "ZONE", id: zone },
      targets: targets.map((t) => ({
        object_type: t.object_type,
        object_id: t.object_id,
        priority: t.priority,
        expected_duration_minutes: t.expected_duration_minutes,
      })),
      constraints,
    };
  };

  // 6.4절 상태모델: 큐에 남은 경로 생성 요청을 온라인 복귀 시 같은 idempotency key로 재전송한다.
  const { tasks: queuedRouteTasks } = useOfflineFlush<RouteCreateRequest>(
    QUEUE_KIND,
    async (payload, idempotencyKey) => {
      const result = await createRoute(payload, { idempotencyKey });
      setRoute(result);
      setStatusMessage("오프라인 상태에서 저장했던 경로 요청이 전송되어 확정되었습니다.");
      return { resultId: result.route_id };
    },
  );

  const pendingRouteTask = queuedRouteTasks.find(
    (task) => task.status === "queued" || task.status === "sending" || task.status === "retryable_error",
  );

  function addTarget() {
    const id = newId.trim();
    if (!id) {
      setError("목적지 ID를 입력해 주세요.");
      return;
    }
    setError(null);
    const next: DraftTarget[] = [
      ...targets,
      {
        clientId: generateClientId(),
        object_type: newType,
        object_id: id,
        label: newLabel.trim() || id,
        priority: targets.length + 1,
        expected_duration_minutes: newDuration === "" ? null : newDuration,
      },
    ];
    setTargets(next);
    writeDraftTargets(next);
    setNewId("");
    setNewLabel("");
    setNewDuration("");
  }

  function removeTarget(clientId: string) {
    const next = targets.filter((t) => t.clientId !== clientId);
    setTargets(next);
    writeDraftTargets(next);
  }

  function moveTarget(clientId: string, direction: -1 | 1) {
    const index = targets.findIndex((t) => t.clientId === clientId);
    if (index === -1) return;
    const target = index + direction;
    if (target < 0 || target >= targets.length) return;
    const next = [...targets];
    const [item] = next.splice(index, 1);
    next.splice(target, 0, item);
    const reordered = next.map((t, i) => ({ ...t, priority: i + 1 }));
    setTargets(reordered);
    writeDraftTargets(reordered);
  }

  function selectZone(zone: string) {
    setCurrentZone(zone);
    const entry = writeLastZone(zone);
    setLastZone(entry);
  }

  async function handleStartRoute() {
    if (isSubmitting) return; // 멱등 제출: 중복 클릭 방지를 위한 버튼 잠금.
    setError(null);
    setStatusMessage(null);
    const request = buildRequest();
    if (!request) return;

    setIsSubmitting(true);
    const idempotencyKey = generateClientId();
    try {
      const result = await createRoute(request, { idempotencyKey });
      setRoute(result);
      setStatusMessage("추천 경로를 시작했습니다.");
    } catch (err) {
      if (err instanceof ApiClientError && (err.code === "NETWORK_ERROR" || err.retryable)) {
        enqueueTask(QUEUE_KIND, request, idempotencyKey);
        setStatusMessage(
          "네트워크에 연결할 수 없어 경로 요청을 저장했습니다. 연결되면 자동으로 다시 보냅니다.",
        );
      } else if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("경로를 시작하지 못했습니다.");
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
      setStatusMessage("경로를 다시 계산했습니다.");
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("경로를 다시 계산하지 못했습니다.");
      }
    } finally {
      setIsRecalculating(false);
    }
  }

  async function toggleAvoidCongestion() {
    const next = !avoidCongestion;
    setAvoidCongestion(next);
    if (route) {
      // 이미 시작한 경로가 있으면 조건 변경 후 즉시 재계산한다 (11.2절 재계산 조건: 혼잡 임계 초과).
      await handleRecalculate();
    }
  }

  return (
    <div className="mx-auto flex max-w-screen-content flex-col gap-6 px-4 py-6">
      <header>
        <h1 className="text-xl font-bold">추천 방문경로</h1>
        <p className="mt-1 text-sm" style={{ color: "var(--color-text-muted)" }}>
          별도 지도 없이 방문 순서를 목록과 텍스트 경로로 안내합니다.
        </p>
      </header>

      {!isOnline ? (
        <div
          role="status"
          aria-live="polite"
          className="rounded-lg border px-4 py-3 text-sm"
          style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
        >
          오프라인 상태입니다. 저장된 최근 경로와 목적지 목록은 계속 볼 수 있고, 경로 시작 요청은
          연결되면 자동으로 전송됩니다.
        </div>
      ) : null}

      {pendingRouteTask ? (
        <div
          role="status"
          aria-live="polite"
          className="rounded-lg border px-4 py-3 text-sm"
          style={{ borderColor: "var(--color-brand)", color: "var(--color-brand)" }}
        >
          {pendingRouteTask.status === "sending"
            ? "저장된 경로 요청을 다시 보내는 중입니다..."
            : "네트워크 연결을 기다리는 경로 요청이 있습니다."}
        </div>
      ) : null}

      <section aria-labelledby="zone-heading" className="flex flex-col gap-3">
        <h2 id="zone-heading" className="text-base font-semibold">
          현재 구역
        </h2>
        {lastZone ? (
          <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
            최근 QR: {lastZone.zone} · {formatObservedAt(lastZone.observedAt)}
          </p>
        ) : (
          <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
            최근 확인된 구역이 없습니다. QR 체크인 또는 아래에서 구역을 직접 선택해 주세요.
          </p>
        )}
        <div className="flex flex-wrap gap-2" role="group" aria-label="구역 빠른 선택">
          {ZONE_PRESETS.map((zone) => (
            <button
              key={zone}
              type="button"
              onClick={() => selectZone(zone)}
              className="tap-target rounded-full border px-4 py-2 text-sm"
              aria-pressed={currentZone === zone}
              style={{
                borderColor: currentZone === zone ? "var(--color-brand)" : "var(--color-border)",
                backgroundColor: currentZone === zone ? "var(--color-brand)" : "var(--color-surface)",
                color: currentZone === zone ? "var(--color-brand-contrast)" : "var(--color-text)",
                fontWeight: currentZone === zone ? 700 : 500,
              }}
            >
              {zone}
            </button>
          ))}
        </div>
        <label className="flex flex-col gap-1 text-sm">
          <span>직접 입력</span>
          <input
            type="text"
            value={currentZone}
            onChange={(event) => setCurrentZone(event.target.value)}
            placeholder="예: D구역 입구"
            className="rounded-lg border px-3 py-2 text-base"
            style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
          />
        </label>
      </section>

      <section aria-labelledby="targets-heading" className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 id="targets-heading" className="text-base font-semibold">
            방문 순서 (목록·텍스트 경로)
          </h2>
          <span className="text-sm" style={{ color: "var(--color-text-muted)" }}>
            {targets.length}곳
          </span>
        </div>

        {targets.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
            아직 추가된 목적지가 없습니다. 아래에서 부스·제품·상담을 추가해 보세요.
          </p>
        ) : (
          <ol className="flex flex-col gap-2">
            {targets.map((target, index) => {
              const routeItem: RouteItemView | undefined = route?.items[index];
              return (
                <li
                  key={target.clientId}
                  className="rounded-lg border p-3"
                  style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex flex-col gap-0.5">
                      <span className="text-sm font-semibold">
                        {index + 1}. {target.label}
                      </span>
                      <span className="text-xs" style={{ color: "var(--color-text-muted)" }}>
                        {OBJECT_TYPE_LABEL[target.object_type]} · {target.object_id}
                        {target.expected_duration_minutes
                          ? ` · 체류 약 ${target.expected_duration_minutes}분`
                          : ""}
                      </span>
                      {routeItem ? (
                        <span className="text-xs" style={{ color: "var(--color-text-muted)" }}>
                          도착 예상 {formatTime(routeItem.expected_arrival_at)} ·{" "}
                          {ROUTE_ITEM_STATUS_LABEL[routeItem.status] ?? routeItem.status}
                        </span>
                      ) : null}
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => moveTarget(target.clientId, -1)}
                        disabled={index === 0}
                        aria-label={`${target.label} 순서를 앞으로 이동`}
                        className="tap-target rounded-full border disabled:opacity-40"
                        style={{ borderColor: "var(--color-border)" }}
                      >
                        ▲
                      </button>
                      <button
                        type="button"
                        onClick={() => moveTarget(target.clientId, 1)}
                        disabled={index === targets.length - 1}
                        aria-label={`${target.label} 순서를 뒤로 이동`}
                        className="tap-target rounded-full border disabled:opacity-40"
                        style={{ borderColor: "var(--color-border)" }}
                      >
                        ▼
                      </button>
                      <button
                        type="button"
                        onClick={() => removeTarget(target.clientId)}
                        aria-label={`${target.label} 경로에서 제거`}
                        className="tap-target rounded-full border"
                        style={{ borderColor: "var(--color-border)", color: "var(--color-danger)" }}
                      >
                        ✕
                      </button>
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        )}

        <fieldset className="flex flex-col gap-2 rounded-lg border p-3" style={{ borderColor: "var(--color-border)" }}>
          <legend className="px-1 text-sm font-medium">목적지 추가</legend>
          <div className="flex flex-wrap gap-2">
            <select
              value={newType}
              onChange={(event) => setNewType(event.target.value as RouteTargetInput["object_type"])}
              className="rounded-lg border px-3 py-2 text-sm"
              style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
              aria-label="목적지 유형"
            >
              {(Object.keys(OBJECT_TYPE_LABEL) as RouteTargetInput["object_type"][]).map((type) => (
                <option key={type} value={type}>
                  {OBJECT_TYPE_LABEL[type]}
                </option>
              ))}
            </select>
            <input
              type="text"
              value={newId}
              onChange={(event) => setNewId(event.target.value)}
              placeholder="ID (예: booth_012)"
              className="min-w-0 flex-1 rounded-lg border px-3 py-2 text-sm"
              style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
              aria-label="목적지 ID"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <input
              type="text"
              value={newLabel}
              onChange={(event) => setNewLabel(event.target.value)}
              placeholder="표시 이름 (예: A양조장)"
              className="min-w-0 flex-1 rounded-lg border px-3 py-2 text-sm"
              style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
              aria-label="표시 이름"
            />
            <input
              type="number"
              min={0}
              value={newDuration}
              onChange={(event) =>
                setNewDuration(event.target.value === "" ? "" : Number(event.target.value))
              }
              placeholder="예상 체류(분)"
              className="w-32 rounded-lg border px-3 py-2 text-sm"
              style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
              aria-label="예상 체류 시간(분)"
            />
          </div>
          <button
            type="button"
            onClick={addTarget}
            className="tap-target self-start rounded-lg border px-4 py-2 text-sm font-medium"
            style={{ borderColor: "var(--color-brand)", color: "var(--color-brand)" }}
          >
            + 목적지 추가
          </button>
        </fieldset>
      </section>

      <section aria-labelledby="constraints-heading" className="flex flex-col gap-3">
        <h2 id="constraints-heading" className="text-base font-semibold">
          경로 조건
        </h2>
        <label className="flex flex-col gap-1 text-sm">
          <span>남은 시간(분)</span>
          <input
            type="number"
            min={0}
            value={availableMinutes}
            onChange={(event) =>
              setAvailableMinutes(event.target.value === "" ? "" : Number(event.target.value))
            }
            className="w-32 rounded-lg border px-3 py-2 text-base"
            style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={minimizeWalking}
            onChange={(event) => setMinimizeWalking(event.target.checked)}
            className="tap-target"
          />
          이동거리 최소화
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={accessibleRoute}
            onChange={(event) => setAccessibleRoute(event.target.checked)}
            className="tap-target"
          />
          이동이 편한 경로(휠체어·유모차 등)
        </label>
      </section>

      {route ? (
        <section
          aria-live="polite"
          className="flex flex-col gap-2 rounded-lg border p-4"
          style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
        >
          <p className="text-sm font-semibold">
            약 {route.total_minutes ?? "?"}분 · 이동 {route.walking_minutes ?? "?"}분
          </p>
          <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
            경로 상태: {ROUTE_STATUS_LABEL[route.status] ?? route.status}
          </p>
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

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={handleStartRoute}
          disabled={isSubmitting}
          className="tap-target rounded-lg px-5 py-3 text-sm font-semibold disabled:opacity-60"
          style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
        >
          {isSubmitting ? "경로 시작 중..." : route ? "경로 다시 시작" : "경로 시작"}
        </button>
        {route ? (
          <button
            type="button"
            onClick={handleRecalculate}
            disabled={isRecalculating}
            className="tap-target rounded-lg border px-5 py-3 text-sm font-semibold disabled:opacity-60"
            style={{ borderColor: "var(--color-border)" }}
          >
            {isRecalculating ? "다시 계산 중..." : "다시 계산"}
          </button>
        ) : null}
        <button
          type="button"
          onClick={toggleAvoidCongestion}
          aria-pressed={avoidCongestion}
          className="tap-target rounded-lg border px-5 py-3 text-sm font-semibold"
          style={{
            borderColor: avoidCongestion ? "var(--color-brand)" : "var(--color-border)",
            color: avoidCongestion ? "var(--color-brand)" : "var(--color-text)",
          }}
        >
          혼잡 부스 제외 {avoidCongestion ? "적용됨" : ""}
        </button>
      </div>
    </div>
  );
}
