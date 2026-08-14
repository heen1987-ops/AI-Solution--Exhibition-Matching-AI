"use client";

/**
 * "비교함" 선택 상태 (최대 4곳) - 매칭 결과 카드와 비교 화면이 공유한다.
 *
 * 요구사항 (작업 지시 원문)
 * --------------------------
 * "compare-up-to-4 button" (매칭 결과 화면), "side-by-side up to 4 exhibitors" (비교 화면).
 * 두 화면이 같은 선택 목록을 봐야 하므로 React Context + `sessionStorage`로 화면 이동 간
 * 상태를 보존한다(로그인 세션 자체를 쓰지 않는 익명 방문 흐름과 동일하게 세션 범위로만
 * 유지 - 방문 종료 후 자동 정리).
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { MAX_COMPARISON_ITEMS } from "./types";

const STORAGE_KEY = "buyer.comparison-selection.v1";

interface ComparisonSelectionValue {
  selectedIds: string[];
  isSelected: (exhibitorId: string) => boolean;
  toggle: (exhibitorId: string) => { added: boolean; blockedByLimit: boolean };
  remove: (exhibitorId: string) => void;
  clear: () => void;
  isFull: boolean;
}

const ComparisonSelectionContext = createContext<ComparisonSelectionValue | null>(null);

function readStored(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) && parsed.every((item) => typeof item === "string")
      ? parsed.slice(0, MAX_COMPARISON_ITEMS)
      : [];
  } catch {
    return [];
  }
}

export function ComparisonSelectionProvider({ children }: { children: ReactNode }) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  useEffect(() => {
    setSelectedIds(readStored());
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(selectedIds));
  }, [selectedIds]);

  const isSelected = useCallback((exhibitorId: string) => selectedIds.includes(exhibitorId), [selectedIds]);

  const toggle = useCallback(
    (exhibitorId: string) => {
      let added = false;
      let blockedByLimit = false;
      setSelectedIds((prev) => {
        if (prev.includes(exhibitorId)) {
          return prev.filter((id) => id !== exhibitorId);
        }
        if (prev.length >= MAX_COMPARISON_ITEMS) {
          blockedByLimit = true;
          return prev;
        }
        added = true;
        return [...prev, exhibitorId];
      });
      return { added, blockedByLimit };
    },
    [],
  );

  const remove = useCallback((exhibitorId: string) => {
    setSelectedIds((prev) => prev.filter((id) => id !== exhibitorId));
  }, []);

  const clear = useCallback(() => setSelectedIds([]), []);

  const value = useMemo<ComparisonSelectionValue>(
    () => ({
      selectedIds,
      isSelected,
      toggle,
      remove,
      clear,
      isFull: selectedIds.length >= MAX_COMPARISON_ITEMS,
    }),
    [selectedIds, isSelected, toggle, remove, clear],
  );

  return <ComparisonSelectionContext.Provider value={value}>{children}</ComparisonSelectionContext.Provider>;
}

export function useComparisonSelection(): ComparisonSelectionValue {
  const ctx = useContext(ComparisonSelectionContext);
  if (!ctx) {
    throw new Error("useComparisonSelection은 ComparisonSelectionProvider 내부에서만 쓸 수 있어요.");
  }
  return ctx;
}
