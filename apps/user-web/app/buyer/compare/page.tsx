"use client";

/**
 * 업체 비교 화면 (WAVE 2C USER-WEB-BUYER). 최대 4곳, `?ids=` 쿼리스트링으로 진입한다
 * (매칭 결과 화면의 "비교하기" 플로팅 버튼이 이 경로로 링크한다).
 */

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { fetchComparisonExhibitors } from "@/features/exhibitor-comparison/api";
import ComparisonTable from "@/features/exhibitor-comparison/ComparisonTable";
import {
  ComparisonSelectionProvider,
  useComparisonSelection,
} from "@/features/exhibitor-comparison/comparison-selection";
import { MAX_COMPARISON_ITEMS, type ComparisonExhibitor } from "@/features/exhibitor-comparison/types";

type LoadState = "loading" | "loaded" | "empty" | "error";

function BuyerCompareContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const comparison = useComparisonSelection();

  const idsParam = searchParams.get("ids");
  const requestedIds = (idsParam ? idsParam.split(",") : comparison.selectedIds)
    .map((id) => id.trim())
    .filter(Boolean)
    .slice(0, MAX_COMPARISON_ITEMS);

  const [exhibitors, setExhibitors] = useState<ComparisonExhibitor[]>([]);
  const [failedIds, setFailedIds] = useState<string[]>([]);
  const [state, setState] = useState<LoadState>("loading");

  useEffect(() => {
    if (requestedIds.length === 0) {
      setState("empty");
      return;
    }
    let cancelled = false;
    setState("loading");
    fetchComparisonExhibitors(requestedIds)
      .then((result) => {
        if (cancelled) return;
        setExhibitors(result.exhibitors);
        setFailedIds(result.failedIds);
        setState(result.exhibitors.length === 0 ? "empty" : "loaded");
      })
      .catch(() => {
        if (!cancelled) setState("error");
      });
    return () => {
      cancelled = true;
    };
    // requestedIds는 매 렌더 새 배열이라 idsParam 문자열로 의존성을 좁힌다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsParam]);

  function handleRemove(exhibitorId: string) {
    comparison.remove(exhibitorId);
    setExhibitors((prev) => prev.filter((item) => item.exhibitor_id !== exhibitorId));
    const remaining = requestedIds.filter((id) => id !== exhibitorId);
    if (remaining.length === 0) {
      setState("empty");
    } else {
      router.replace(`/buyer/compare?ids=${remaining.map(encodeURIComponent).join(",")}`);
    }
  }

  return (
    <div className="mx-auto flex max-w-screen-content flex-col gap-4 px-4 py-4">
      <header>
        <h1 className="text-xl font-bold">업체 비교</h1>
        <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
          최대 4곳까지 나란히 비교할 수 있어요. 아직 확인되지 않은 정보는 &ldquo;확인
          필요&rdquo;로 표시돼요.
        </p>
      </header>

      {state === "loading" ? (
        <p role="status" aria-live="polite" className="text-sm" style={{ color: "var(--color-text-muted)" }}>
          비교 정보를 불러오는 중이에요...
        </p>
      ) : null}

      {state === "error" ? (
        <p role="alert" style={{ color: "var(--color-danger)" }}>
          비교 정보를 불러오지 못했어요.
        </p>
      ) : null}

      {state === "empty" ? (
        <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
          비교할 업체가 없어요. 매칭 결과 화면에서 &ldquo;비교하기&rdquo;로 업체를 담아 주세요.
        </p>
      ) : null}

      {state === "loaded" ? <ComparisonTable exhibitors={exhibitors} onRemove={handleRemove} /> : null}

      {failedIds.length > 0 ? (
        <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
          {failedIds.length}곳은 정보를 불러오지 못해 비교표에서 제외했어요.
        </p>
      ) : null}
    </div>
  );
}

export default function BuyerComparePage() {
  return (
    <ComparisonSelectionProvider>
      {/* `useSearchParams`는 Next.js App Router에서 Suspense 경계가 필요하다. */}
      <Suspense
        fallback={
          <p role="status" className="px-4 py-8 text-center text-sm" style={{ color: "var(--color-text-muted)" }}>
            불러오는 중이에요...
          </p>
        }
      >
        <BuyerCompareContent />
      </Suspense>
    </ComparisonSelectionProvider>
  );
}
