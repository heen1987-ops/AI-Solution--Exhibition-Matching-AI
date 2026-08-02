/**
 * 오프라인 로컬 큐 - U-13~U-17 공용.
 *
 * 근거 문서
 * ---------
 * - docs/user-ia-wireframes.md 6.4절(오프라인 동기화 상태모델):
 *     `local_only → queued → sending → synced`
 *     `sending → retryable_error → queued`
 *     `sending → final_error`
 *   이 파일의 `QueueStatus`와 `flushQueue`의 전이 로직이 이 상태모델을 그대로 구현한다.
 * - docs/user-ia-wireframes.md 11.4절(네트워크 단절):
 *   "QR 체크인·피드백·상담요청은 멱등 키와 함께 로컬 큐에 임시저장", "재연결 시 자동
 *   재전송하고 성공·실패 상태를 사용자에게 표시", "연락처·동의 원문 등 민감정보는 브라우저
 *   캐시에 저장하지 않음" - 이 큐는 이미 구성된 API 요청 바디(payload)만 저장하며, 호출하는
 *   화면이 상담 자유메모·연락처 원문처럼 민감한 필드를 payload에 넣지 않도록 주의해야 한다.
 * - docs/frontend-backend-ai-interface-spec.md 4.2절: "같은 키·같은 주체·같은 경로·같은
 *   요청 본문은 최초 결과를 재사용한다" - 큐에 넣은 항목은 재전송 시 항상 동일한
 *   `idempotencyKey`(=`id`)와 동일한 payload로 다시 보내야 하므로, 이 파일은 큐 항목의
 *   payload를 절대 변형하지 않고 그대로 재사용한다.
 *
 * 스코프 메모: 이 파일은 U-13(경로)~U-17(피드백) 담당 에이전트가 자신의 화면에서만 쓰려고
 * 새로 만든 보조 파일이며, 공용 aggregator 파일(app/api/v1/api.py, app/main.py,
 * frontend/lib/api-client.ts)이 아니다.
 *
 * 큐는 페이지가 마운트되어 있는 동안에만 재전송을 시도한다(백그라운드 서비스워커 동기화는
 * 이 저장소에 아직 없다 - TODO: 이후 서비스워커 `sync` 이벤트로 승격).
 */

import { useCallback, useEffect, useState } from "react";

import { ApiClientError } from "./api-client";

export type QueueStatus =
  | "local_only"
  | "queued"
  | "sending"
  | "synced"
  | "retryable_error"
  | "final_error";

export interface QueueItem<TPayload = unknown> {
  /** 멱등키로도 재사용한다 (Idempotency-Key). */
  id: string;
  /** 큐 종류 구분자. 예: `CHECK_IN`, `FEEDBACK`, `MEETING_REQUEST`, `MEETING_ACTION`, `ROUTE_CREATE`. */
  kind: string;
  payload: TPayload;
  status: QueueStatus;
  attempts: number;
  createdAt: string;
  updatedAt: string;
  lastError: string | null;
  /** 화면이 재전송 완료 후 참조할 결과 식별자(예: 생성된 meeting_id). */
  resultId: string | null;
}

const STORAGE_KEY = "backju.offline_queue.v1";

function isBrowser(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function nowIso(): string {
  return new Date().toISOString();
}

function loadAll(): QueueItem[] {
  if (!isBrowser()) return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as QueueItem[]) : [];
  } catch {
    return [];
  }
}

function saveAll(items: QueueItem[]): void {
  if (!isBrowser()) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  } catch {
    // 저장 공간 부족 등은 조용히 무시한다 - 오프라인 큐는 최선 노력 기능이다.
  }
}

/** 이미 같은 id로 큐에 있으면 그 항목을 반환하고, 없으면 `queued` 상태로 새로 만든다. */
export function enqueueTask<T>(kind: string, payload: T, id: string): QueueItem<T> {
  const items = loadAll();
  const existing = items.find((item) => item.id === id);
  if (existing) return existing as QueueItem<T>;

  const item: QueueItem<T> = {
    id,
    kind,
    payload,
    status: "queued",
    attempts: 0,
    createdAt: nowIso(),
    updatedAt: nowIso(),
    lastError: null,
    resultId: null,
  };
  saveAll([...items, item as QueueItem]);
  return item;
}

export function listTasks(kind?: string): QueueItem[] {
  const items = loadAll();
  return kind ? items.filter((item) => item.kind === kind) : items;
}

export function getTask(id: string): QueueItem | undefined {
  return loadAll().find((item) => item.id === id);
}

export function updateTask(id: string, patch: Partial<QueueItem>): void {
  const items = loadAll();
  const next = items.map((item) =>
    item.id === id ? { ...item, ...patch, updatedAt: nowIso() } : item,
  );
  saveAll(next);
}

export function removeTask(id: string): void {
  saveAll(loadAll().filter((item) => item.id !== id));
}

/** 네트워크 단절/서버 일시 오류처럼 "나중에 다시 시도하면 될" 오류인지 판별한다. */
export function isRetryableError(err: unknown): boolean {
  if (err instanceof ApiClientError) {
    return err.code === "NETWORK_ERROR" || err.retryable;
  }
  return false;
}

/** 특정 종류의 큐를 한 번 훑어 대기 중인 항목을 재전송한다 (6.4절 상태 전이). */
export async function flushQueue<T>(
  kind: string,
  send: (payload: T, idempotencyKey: string) => Promise<{ resultId?: string | null } | void>,
): Promise<void> {
  const pending = listTasks(kind).filter(
    (item) => item.status === "queued" || item.status === "retryable_error",
  );
  for (const item of pending) {
    updateTask(item.id, { status: "sending" });
    try {
      const result = await send(item.payload as T, item.id);
      updateTask(item.id, {
        status: "synced",
        resultId: (result && "resultId" in result ? result.resultId : null) ?? null,
        lastError: null,
      });
    } catch (err) {
      const retryable = isRetryableError(err);
      updateTask(item.id, {
        status: retryable ? "retryable_error" : "final_error",
        attempts: item.attempts + 1,
        lastError: err instanceof Error ? err.message : "알 수 없는 오류가 발생했습니다.",
      });
      // 여전히 오프라인으로 보이면 나머지 항목도 뒤로 미룬다(연속 실패 방지).
      if (retryable) break;
    }
  }
}

/**
 * 페이지가 마운트된 동안 특정 큐 종류를 온라인 복귀·주기적으로 재전송하는 훅.
 * `deps`가 바뀌면(예: send 함수가 최신 상태를 캡처해야 할 때) 다시 구독한다.
 */
export function useOfflineFlush<T>(
  kind: string,
  send: (payload: T, idempotencyKey: string) => Promise<{ resultId?: string | null } | void>,
  intervalMs = 15000,
): { tasks: QueueItem<T>[]; refresh: () => void } {
  const [tasks, setTasks] = useState<QueueItem<T>[]>([]);

  const refresh = useCallback(() => {
    setTasks(listTasks(kind) as QueueItem<T>[]);
  }, [kind]);

  useEffect(() => {
    refresh();
    let cancelled = false;

    async function run() {
      await flushQueue<T>(kind, send);
      if (!cancelled) refresh();
    }

    void run();
    const handleOnline = () => void run();
    window.addEventListener("online", handleOnline);
    const interval = window.setInterval(() => void run(), intervalMs);

    return () => {
      cancelled = true;
      window.removeEventListener("online", handleOnline);
      window.clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, intervalMs, refresh]);

  return { tasks, refresh };
}

/** 브라우저 온라인 여부를 구독하는 작은 훅 (TopBar와 별개로 화면 로컬 배너에 쓴다). */
export function useIsOnline(): boolean {
  const [isOnline, setIsOnline] = useState(true);
  useEffect(() => {
    setIsOnline(typeof navigator === "undefined" ? true : navigator.onLine);
    const on = () => setIsOnline(true);
    const off = () => setIsOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  return isOnline;
}
