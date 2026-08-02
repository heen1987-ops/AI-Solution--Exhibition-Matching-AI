"use client";

/**
 * U-09 추천 전체.
 *
 * 근거 문서
 * ---------
 * - docs/user-ia-wireframes.md 5.1절: 경로 `/recommendations`, 핵심 API
 *   `GET /recommendations` - 실제 계약은 인터페이스 명세 9.4절
 *   `GET /recommendation-sessions/{id}/items?type=&sort=&cursor=&limit=`이며
 *   `frontend/lib/api-client.ts`의 `getRecommendationSessionItems`를 그대로 쓴다. 세션
 *   ID가 없으면 먼저 `getRecommendations()`(홈, 9.3절)로 발급받는다.
 * - 7절 U-09 와이어프레임: 유형 탭([부스][제품][상담][행사]), 정렬([추천][거리][대기]),
 *   필터(주종·가격·구매·시음) 레이아웃의 1차 근거.
 * - `RecommendationListQuery.type`은 `RecommendableObjectType`(BOOTH/PRODUCT/EXHIBITOR/
 *   PROGRAM)만 받는다. 와이어프레임의 "상담" 탭은 별도 object_type이 아니라 EXHIBITOR
 *   대상 추천(상담이 recommended_action인 경우가 많음)에 대응시킨 근사치다 - 문서가
 *   "상담"이라는 별도 API 값을 정의하지 않아서다.
 * - "필터 주종 · 가격 · 구매 · 시음" 중 `구매`/`시음`은 `RecommendationItem.availability`로
 *   클라이언트에서 바로 걸러낼 수 있어 동작하게 구현한다. `주종`/`가격`은 추천 목록 API
 *   응답에 해당 필드가 없어(업체·제품 상세를 개별 조회해야 함) 임의로 지어내지 않고
 *   "준비 중"으로 비활성 처리한다. TODO(추천 API가 taxonomy/가격 요약 필드를 제공하면
 *   대조해 구현).
 * - 9.4절: "만료된 추천은 조회할 수 있으나 stale:true와 새 추천 액션을 반환한다" - 목록이
 *   stale이면 새 추천 생성(`createRecommendationSession`) 액션을 보여준다.
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";

import {
  ApiClientError,
  createRecommendationSession,
  getRecommendationSessionItems,
  getRecommendations,
} from "@/lib/api-client";
import type { RecommendableObjectType, RecommendationItem, RecommendationSort } from "@/lib/types";

import RecommendationCard from "@/components/RecommendationCard";

type LoadState = "loading" | "loaded" | "empty" | "error";

interface TypeTab {
  value: RecommendableObjectType | undefined;
  label: string;
}

const TYPE_TABS: TypeTab[] = [
  { value: undefined, label: "전체" },
  { value: "BOOTH", label: "부스" },
  { value: "PRODUCT", label: "제품" },
  { value: "EXHIBITOR", label: "상담" },
  { value: "PROGRAM", label: "행사" },
];

const SORT_TABS: { value: RecommendationSort; label: string }[] = [
  { value: "RECOMMENDED", label: "추천" },
  { value: "DISTANCE", label: "거리" },
  { value: "WAIT", label: "대기" },
];

function ChipButton({
  active,
  disabled,
  onClick,
  children,
}: {
  active: boolean;
  disabled?: boolean;
  onClick?: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={active}
      className="tap-target rounded-full border px-3 text-sm font-semibold disabled:opacity-50"
      style={{
        borderColor: active ? "var(--color-brand)" : "var(--color-border)",
        backgroundColor: active ? "var(--color-brand)" : "transparent",
        color: active ? "var(--color-brand-contrast)" : "var(--color-text)",
      }}
    >
      {children}
    </button>
  );
}

export default function RecommendationsPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<RecommendableObjectType | undefined>(undefined);
  const [sort, setSort] = useState<RecommendationSort>("RECOMMENDED");
  const [purchaseOnly, setPurchaseOnly] = useState(false);
  const [tastingOnly, setTastingOnly] = useState(false);

  const [items, setItems] = useState<RecommendationItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<ApiClientError | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const ensureSession = useCallback(async (): Promise<string> => {
    if (sessionId) return sessionId;
    const home = await getRecommendations();
    setSessionId(home.recommendation_session_id);
    return home.recommendation_session_id;
  }, [sessionId]);

  const fetchItems = useCallback(
    async (options: { reset: boolean; cursor?: string | null }) => {
      if (options.reset) {
        setState("loading");
        setError(null);
      } else {
        setLoadingMore(true);
      }
      try {
        const id = await ensureSession();
        const page = await getRecommendationSessionItems(id, {
          type: typeFilter,
          sort,
          cursor: options.cursor ?? undefined,
          limit: 20,
        });
        setItems((prev) => (options.reset ? page.items : [...prev, ...page.items]));
        setNextCursor(page.next_cursor);
        setStale(page.stale);
        setState(options.reset && page.items.length === 0 ? "empty" : "loaded");
      } catch (err) {
        if (err instanceof ApiClientError && err.code === "NO_CANDIDATE") {
          setItems([]);
          setState("empty");
        } else {
          setError(err instanceof ApiClientError ? err : null);
          setState("error");
        }
      } finally {
        setLoadingMore(false);
      }
    },
    [ensureSession, typeFilter, sort],
  );

  // 탭·정렬이 바뀌면 처음부터 다시 조회한다(서버가 이미 type/sort로 필터링해 준다).
  useEffect(() => {
    void fetchItems({ reset: true, cursor: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typeFilter, sort]);

  async function handleRefreshStale() {
    setRefreshing(true);
    try {
      const response = await createRecommendationSession({ recommendation_type: "MIXED" });
      setSessionId(response.recommendation_session_id);
      const page = await getRecommendationSessionItems(response.recommendation_session_id, {
        type: typeFilter,
        sort,
        limit: 20,
      });
      setItems(page.items);
      setNextCursor(page.next_cursor);
      setStale(page.stale);
      setState(page.items.length === 0 ? "empty" : "loaded");
    } catch (err) {
      setError(err instanceof ApiClientError ? err : null);
      setState("error");
    } finally {
      setRefreshing(false);
    }
  }

  const visibleItems = items.filter((item) => {
    if (purchaseOnly && !item.availability.purchase) return false;
    if (tastingOnly && !item.availability.tasting) return false;
    return true;
  });

  return (
    <div className="mx-auto max-w-screen-content space-y-4 px-4 py-4">
      <h1 className="text-xl font-bold">나를 위한 추천</h1>

      <div role="tablist" aria-label="추천 대상 유형" className="flex flex-wrap gap-2">
        {TYPE_TABS.map((tab) => (
          <ChipButton
            key={tab.label}
            active={typeFilter === tab.value}
            onClick={() => setTypeFilter(tab.value)}
          >
            {tab.label}
          </ChipButton>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold" style={{ color: "var(--color-text-muted)" }}>
          정렬
        </span>
        <div role="tablist" aria-label="정렬 기준" className="flex flex-wrap gap-2">
          {SORT_TABS.map((tab) => (
            <ChipButton key={tab.value} active={sort === tab.value} onClick={() => setSort(tab.value)}>
              {tab.label}
            </ChipButton>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold" style={{ color: "var(--color-text-muted)" }}>
          필터
        </span>
        <ChipButton disabled active={false}>
          주종 (준비 중)
        </ChipButton>
        <ChipButton disabled active={false}>
          가격 (준비 중)
        </ChipButton>
        <ChipButton active={purchaseOnly} onClick={() => setPurchaseOnly((value) => !value)}>
          구매 가능만
        </ChipButton>
        <ChipButton active={tastingOnly} onClick={() => setTastingOnly((value) => !value)}>
          시음 가능만
        </ChipButton>
      </div>

      {stale && state === "loaded" ? (
        <div
          className="flex items-center justify-between gap-3 rounded-xl border p-3 text-sm"
          style={{ borderColor: "var(--color-border)", color: "var(--color-text-muted)" }}
        >
          <span>최신 정보가 아닐 수 있어요.</span>
          <button
            type="button"
            onClick={() => void handleRefreshStale()}
            disabled={refreshing}
            className="tap-target rounded-lg border px-3 font-semibold disabled:opacity-60"
            style={{ borderColor: "var(--color-border)", color: "var(--color-text)" }}
          >
            {refreshing ? "새로고침 중" : "새 추천 만들기"}
          </button>
        </div>
      ) : null}

      {state === "loading" ? (
        <div className="space-y-3" aria-hidden="true">
          {[0, 1, 2].map((key) => (
            <div key={key} className="animate-pulse rounded-2xl border p-4" style={{ borderColor: "var(--color-border)" }}>
              <div className="h-5 w-2/3 rounded" style={{ backgroundColor: "var(--color-border)" }} />
              <div className="mt-2 h-4 w-1/2 rounded" style={{ backgroundColor: "var(--color-border)" }} />
            </div>
          ))}
        </div>
      ) : null}

      {state === "error" ? (
        <div role="alert" className="rounded-2xl border p-4" style={{ borderColor: "var(--color-border)" }}>
          <p className="font-semibold" style={{ color: "var(--color-danger)" }}>
            {error?.code === "NETWORK_ERROR"
              ? "서버에 연결할 수 없어요. 네트워크 상태를 확인해 주세요."
              : (error?.message ?? "추천을 불러오지 못했어요.")}
          </p>
          <button
            type="button"
            onClick={() => void fetchItems({ reset: true, cursor: null })}
            className="tap-target mt-3 rounded-lg border px-4 text-sm font-semibold"
            style={{ borderColor: "var(--color-border)" }}
          >
            다시 시도
          </button>
        </div>
      ) : null}

      {state === "empty" ? (
        <div className="rounded-2xl border p-4" style={{ borderColor: "var(--color-border)" }}>
          <p className="font-semibold">이 조건에 맞는 추천이 아직 없어요.</p>
          <p className="mt-1 text-sm" style={{ color: "var(--color-text-muted)" }}>
            다른 유형·정렬을 선택하거나 필터를 해제해 보세요.
          </p>
        </div>
      ) : null}

      {state === "loaded" && visibleItems.length === 0 ? (
        <div className="rounded-2xl border p-4" style={{ borderColor: "var(--color-border)" }}>
          <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
            선택한 필터에 맞는 항목이 없어요. 필터를 해제해 보세요.
          </p>
        </div>
      ) : null}

      {state === "loaded"
        ? visibleItems.map((item) => (
            <RecommendationCard
              key={`${item.object_type}-${item.object_id}-${item.rank}`}
              item={item}
              recommendationSessionId={sessionId}
              screen="EXPLORE"
              stale={false}
            />
          ))
        : null}

      {state === "loaded" && nextCursor ? (
        <button
          type="button"
          onClick={() => void fetchItems({ reset: false, cursor: nextCursor })}
          disabled={loadingMore}
          className="tap-target w-full rounded-lg border px-4 text-sm font-semibold disabled:opacity-60"
          style={{ borderColor: "var(--color-border)" }}
        >
          {loadingMore ? "불러오는 중" : "더 보기"}
        </button>
      ) : null}
    </div>
  );
}
