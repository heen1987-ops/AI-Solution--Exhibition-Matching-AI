/**
 * 익명 사용자의 관심목록(저장) 로컬 저장소.
 *
 * 근거 문서
 * ---------
 * - docs/frontend-backend-ai-interface-spec.md 5절(권한·스코프) - "로컬 저장 | GUEST 가능",
 *   "서버 저장·일정 | PHONE_VERIFIED". 즉 휴대전화 인증 전에는 `/favorites` 서버 API 대신
 *   브라우저 로컬 저장소만 쓸 수 있다.
 * - docs/user-ia-wireframes.md U-19절 - "익명 사용자의 저장목록은 브라우저 로컬에 보관하고
 *   인증 시 명시적으로 계정에 합친다."
 * - 작업 지시: "익명 사용자의 저장목록은 브라우저 로컬(localStorage)에 보관하고 인증 시
 *   합치는 로직을 실제로 구현하라."
 *
 * 이 모듈은 `frontend/app/saved/page.tsx`(U-19)가 1차로 쓰지만, 부스·제품 상세(U-10/U-11)
 * 등 다른 화면이 "저장" 버튼을 만들 때도 재사용할 수 있도록 범용으로 설계했다 - 다만 이
 * 작업 범위는 그 화면들을 직접 수정하지 않는다.
 */

import type { RecommendableObjectType } from "./types";
import { ApiClientError, createFavorite } from "./api-client";
import type { FavoriteSource } from "./types";

export interface LocalFavoriteItem {
  /** 서버 favorite_id와 형태를 구분하기 위한 클라이언트 전용 접두사 ID. */
  local_id: string;
  object_type: RecommendableObjectType;
  object_id: string;
  source: FavoriteSource;
  match_result_id: string | null;
  created_at: string;
}

const STORAGE_KEY = "backju:local_favorites:v1";
const EVENT_NAME = "backju:local-favorites-changed";

function generateLocalId(): string {
  const globalCrypto = typeof crypto !== "undefined" ? crypto : undefined;
  if (globalCrypto && typeof globalCrypto.randomUUID === "function") {
    return `local_${globalCrypto.randomUUID()}`;
  }
  return `local_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`;
}

function readAll(): LocalFavoriteItem[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as LocalFavoriteItem[]) : [];
  } catch {
    return [];
  }
}

function writeAll(items: LocalFavoriteItem[]): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  window.dispatchEvent(new Event(EVENT_NAME));
}

export function listLocalFavorites(): LocalFavoriteItem[] {
  return readAll();
}

export function hasLocalFavorites(): boolean {
  return readAll().length > 0;
}

/** 이미 같은 (object_type, object_id)가 있으면 새로 추가하지 않고 기존 항목을 반환한다. */
export function addLocalFavorite(input: {
  object_type: RecommendableObjectType;
  object_id: string;
  source: FavoriteSource;
  match_result_id?: string | null;
}): LocalFavoriteItem {
  const items = readAll();
  const existing = items.find(
    (item) => item.object_type === input.object_type && item.object_id === input.object_id,
  );
  if (existing) return existing;

  const created: LocalFavoriteItem = {
    local_id: generateLocalId(),
    object_type: input.object_type,
    object_id: input.object_id,
    source: input.source,
    match_result_id: input.match_result_id ?? null,
    created_at: new Date().toISOString(),
  };
  writeAll([created, ...items]);
  return created;
}

export function removeLocalFavorite(localId: string): void {
  writeAll(readAll().filter((item) => item.local_id !== localId));
}

export function clearLocalFavorites(): void {
  writeAll([]);
}

/** 같은 탭(커스텀 이벤트) + 다른 탭(storage 이벤트) 변경을 모두 구독한다. */
export function subscribeLocalFavorites(callback: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener("storage", callback);
  window.addEventListener(EVENT_NAME, callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(EVENT_NAME, callback);
  };
}

export interface MergeLocalFavoritesResult {
  mergedCount: number;
  failed: Array<{ item: LocalFavoriteItem; message: string }>;
}

/**
 * 휴대전화 인증(PHONE_VERIFIED 이상) 직후 호출한다. 로컬 항목을 하나씩 `POST /favorites`로
 * 전송하고, 성공한 항목만 로컬에서 제거한다(부분 실패해도 나머지는 다음 기회에 재시도할 수
 * 있도록 로컬에 남겨 둔다).
 */
export async function mergeLocalFavoritesToServer(): Promise<MergeLocalFavoritesResult> {
  const items = readAll();
  const failed: MergeLocalFavoritesResult["failed"] = [];
  let mergedCount = 0;

  for (const item of items) {
    try {
      await createFavorite({
        object_type: item.object_type,
        object_id: item.object_id,
        source: item.source,
        match_result_id: item.match_result_id,
      });
      removeLocalFavorite(item.local_id);
      mergedCount += 1;
    } catch (error) {
      failed.push({
        item,
        message: error instanceof ApiClientError ? error.message : "저장 항목을 합치지 못했습니다.",
      });
    }
  }

  return { mergedCount, failed };
}
