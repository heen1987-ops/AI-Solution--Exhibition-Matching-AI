"use client";

/**
 * U-10 부스 상세.
 *
 * 근거 문서
 * ---------
 * - docs/user-ia-wireframes.md 5.1절: 경로 `/booths/{boothId}`, 진입 조건 "없음"(개인화
 *   동의 없이도 열람 가능), 핵심 API `GET /booths/{id}` -
 *   `frontend/lib/api-client.ts`의 `getBooth(boothId, { matchResultId })`를 그대로 쓴다.
 * - 7절 U-10 필수 영역: "업체명, 부스번호, 거리 또는 구역 / 검수된 대표 이미지와 소개 /
 *   사용자의 추천 근거 / 대표 제품, 주종, 가격대 / 현재 가능한 행동(시음·구매·상담) /
 *   운영·혼잡·품절 상태와 갱신시각 / 지도, 일정 추가, 상담 요청, 저장"의 1차 근거.
 *   "운영정보가 없거나 오래된 경우 `현재 상태 미확인`으로 표시한다"는
 *   `OperatingStatusBadge`의 자동 신선도 판정으로 처리한다.
 * - 인터페이스 명세 10.1절: `match_result_id`는 선택이며 "소유권이 확인될 때만 개인화
 *   이유를 포함한다" - URL 쿼리 `?matchResultId=`로 전달하고, 서버가 소유권을 검증하지
 *   못하면 `recommendation_context.reasons`가 빈 배열로 온다(이 화면은 별도 처리 없이
 *   빈 배열이면 추천 근거 섹션을 숨긴다).
 * - `BoothDetailResponse`(frontend/lib/types.ts)에는 이미지 URL 필드가 없어(설계 문서
 *   예시 JSON에도 없음) 이미지를 지어내지 않고 플레이스홀더로 대체한다.
 * - `BoothProductSummary`(대표 제품)에는 재고 상태 필드가 없어(가격만 있음) 품절 배지는
 *   보여주지 않는다 - TODO(제품별 재고를 부스 상세에 포함하도록 백엔드 확정 후 대조).
 * - 11.2절(운영 종료·품절) - 선택한 대상의 상태·갱신시각을 보여주고 대체를 제시한다.
 *   이 화면은 상태·갱신시각까지 구현하고, 대체 부스 추천은 `/recommendations`로 안내한다.
 */

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ApiClientError, createFavorite, deleteFavorite, getBooth, postInteraction } from "@/lib/api-client";
import type { BoothDetailResponse, PriceRange } from "@/lib/types";

import OperatingStatusBadge, { boothOperatingStatusToCode } from "@/components/OperatingStatusBadge";

type LoadState = "loading" | "loaded" | "error";

/** 9.2절에 명시되지 않은 "혼잡" 판정 임계값. `components/RecommendationCard.tsx`와 같은
 * 기본값을 쓴다. TODO(현장 운영 정책 확정 후 대조). */
const CROWDED_WAIT_MINUTES_THRESHOLD = 15;

function formatPrice(price: PriceRange | null | undefined): string {
  if (!price || (price.min_amount == null && price.max_amount == null)) return "가격 문의";
  const formatter = new Intl.NumberFormat("ko-KR");
  if (price.min_amount != null && price.max_amount != null && price.min_amount !== price.max_amount) {
    return `${formatter.format(price.min_amount)}~${formatter.format(price.max_amount)} ${price.currency}`;
  }
  const amount = price.min_amount ?? price.max_amount;
  return amount != null ? `${formatter.format(amount)} ${price.currency}` : "가격 문의";
}

export default function BoothDetailPage() {
  const params = useParams<{ boothId: string }>();
  const searchParams = useSearchParams();
  const matchResultId = searchParams.get("matchResultId") ?? undefined;

  const [booth, setBooth] = useState<BoothDetailResponse | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<ApiClientError | null>(null);

  const [favoriteId, setFavoriteId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [routeAdded, setRouteAdded] = useState(false);

  const load = useCallback(async () => {
    setState("loading");
    setError(null);
    try {
      const response = await getBooth(params.boothId, { matchResultId });
      setBooth(response);
      setState("loaded");
    } catch (err) {
      setError(err instanceof ApiClientError ? err : null);
      setState("error");
    }
  }, [params.boothId, matchResultId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleToggleSave() {
    if (!booth || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      if (favoriteId) {
        await deleteFavorite(favoriteId);
        setFavoriteId(null);
      } else {
        const favorite = await createFavorite({
          object_type: "BOOTH",
          object_id: booth.booth_id,
          source: matchResultId ? "RECOMMENDATION" : "SEARCH",
          match_result_id: booth.recommendation_context.match_result_id,
        });
        setFavoriteId(favorite.favorite_id);
      }
    } catch (err) {
      setSaveError(err instanceof ApiClientError ? err.message : "저장하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  }

  function handleAddToRoute() {
    if (!booth) return;
    setRouteAdded(true);
    // TODO(U-13 지도·추천 경로 구현 후 대조): 실제 경로 조립(`createRoute`)은 지도 화면이
    // 담당한다. 여기서는 "일정 추가" 의도를 인터랙션 로그로 남긴다.
    void postInteraction({
      event_type: "ROUTE_ITEM_ADDED",
      object_type: "BOOTH",
      object_id: booth.booth_id,
      match_result_id: booth.recommendation_context.match_result_id,
      occurred_at: new Date().toISOString(),
    }).catch(() => {});
  }

  if (state === "loading") {
    return (
      <div className="mx-auto max-w-screen-content space-y-3 px-4 py-4" aria-busy="true">
        <div className="h-40 animate-pulse rounded-2xl" style={{ backgroundColor: "var(--color-border)" }} />
        <div className="h-6 w-1/2 animate-pulse rounded" style={{ backgroundColor: "var(--color-border)" }} />
        <div className="h-4 w-1/3 animate-pulse rounded" style={{ backgroundColor: "var(--color-border)" }} />
      </div>
    );
  }

  if (state === "error" || !booth) {
    return (
      <div className="mx-auto max-w-screen-content px-4 py-4">
        <div role="alert" className="rounded-2xl border p-4" style={{ borderColor: "var(--color-border)" }}>
          <p className="font-semibold" style={{ color: "var(--color-danger)" }}>
            {error?.code === "NETWORK_ERROR"
              ? "서버에 연결할 수 없어요. 네트워크 상태를 확인해 주세요."
              : (error?.message ?? "부스 정보를 불러오지 못했어요.")}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void load()}
              className="tap-target rounded-lg border px-4 text-sm font-semibold"
              style={{ borderColor: "var(--color-border)" }}
            >
              다시 시도
            </button>
            <Link
              href="/recommendations"
              className="tap-target rounded-lg border px-4 text-sm font-semibold"
              style={{ borderColor: "var(--color-border)" }}
            >
              다른 부스 보기
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const showCrowded =
    booth.estimated_wait_minutes != null && booth.estimated_wait_minutes >= CROWDED_WAIT_MINUTES_THRESHOLD;

  return (
    <div className="mx-auto max-w-screen-content space-y-4 px-4 py-4">
      {/* BoothDetailResponse에 이미지 필드가 없어 자리표시자로 대체한다(위 주석 참고). */}
      <div
        className="flex h-32 items-center justify-center rounded-2xl text-sm"
        style={{ backgroundColor: "var(--color-bg)", color: "var(--color-text-muted)", border: "1px dashed var(--color-border)" }}
      >
        이미지 준비 중
      </div>

      <div>
        <h1 className="text-xl font-bold">{booth.exhibitor.name}</h1>
        <p className="mt-1 text-sm" style={{ color: "var(--color-text-muted)" }}>
          {booth.booth_number} · {booth.location.zone}구역
        </p>
      </div>

      {booth.exhibitor.summary ? <p className="text-sm">{booth.exhibitor.summary}</p> : null}

      {booth.recommendation_context.reasons.length > 0 ? (
        <section aria-labelledby="reasons-heading" className="rounded-2xl border p-3" style={{ borderColor: "var(--color-border)" }}>
          <h2 id="reasons-heading" className="text-sm font-bold">
            나에게 맞는 이유
          </h2>
          <ul className="mt-1 space-y-0.5">
            {booth.recommendation_context.reasons.map((reason) => (
              <li key={`${reason.code}-${reason.text}`} className="text-sm">
                · {reason.text}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="status-heading" className="space-y-2">
        <h2 id="status-heading" className="text-sm font-bold" style={{ color: "var(--color-text-muted)" }}>
          현재 상태
        </h2>
        <div className="flex flex-wrap gap-1.5">
          <OperatingStatusBadge
            code={boothOperatingStatusToCode(booth.operating_status)}
            observedAt={booth.status_observed_at}
            showObservedTime
          />
          {booth.services.tasting ? <OperatingStatusBadge code="TASTING_AVAILABLE" /> : null}
          {booth.services.purchase ? <OperatingStatusBadge code="PURCHASE_AVAILABLE" /> : null}
          {booth.services.meeting ? <OperatingStatusBadge code="MEETING_AVAILABLE" /> : null}
          {showCrowded ? <OperatingStatusBadge code="CROWDED" /> : null}
        </div>
        {booth.estimated_wait_minutes != null ? (
          <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
            예상 대기 약 {booth.estimated_wait_minutes}분
          </p>
        ) : null}
      </section>

      {booth.products.length > 0 ? (
        <section aria-labelledby="products-heading" className="space-y-2">
          <h2 id="products-heading" className="text-sm font-bold" style={{ color: "var(--color-text-muted)" }}>
            대표 제품
          </h2>
          <ul className="space-y-2">
            {booth.products.map((product) => (
              <li key={product.product_id}>
                <Link
                  href={`/products/${encodeURIComponent(product.product_id)}`}
                  className="flex items-center justify-between rounded-xl border p-3"
                  style={{ borderColor: "var(--color-border)" }}
                >
                  <span>
                    <span className="block text-sm font-semibold">{product.product_name}</span>
                    {product.category ? (
                      <span className="text-xs" style={{ color: "var(--color-text-muted)" }}>
                        {product.category}
                      </span>
                    ) : null}
                  </span>
                  <span className="text-sm font-semibold">{formatPrice(product.price)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <Link
          href={`/map?boothId=${encodeURIComponent(booth.booth_id)}`}
          className="tap-target rounded-lg border px-4 text-sm font-semibold"
          style={{ borderColor: "var(--color-border)" }}
        >
          지도에서 보기
        </Link>

        <button
          type="button"
          onClick={handleAddToRoute}
          disabled={routeAdded}
          className="tap-target rounded-lg border px-4 text-sm font-semibold disabled:opacity-60"
          style={{ borderColor: "var(--color-border)" }}
        >
          {routeAdded ? "일정에 추가됨" : "일정 추가"}
        </button>

        {booth.services.meeting ? (
          <Link
            href={`/meetings/new?exhibitorId=${encodeURIComponent(booth.exhibitor.exhibitor_id)}`}
            className="tap-target rounded-lg px-4 text-sm font-bold"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
          >
            상담 요청
          </Link>
        ) : null}

        <button
          type="button"
          onClick={handleToggleSave}
          disabled={saving}
          aria-pressed={Boolean(favoriteId)}
          className="tap-target rounded-lg border px-4 text-sm font-semibold disabled:opacity-60"
          style={{
            borderColor: favoriteId ? "var(--color-brand)" : "var(--color-border)",
            color: favoriteId ? "var(--color-brand)" : "var(--color-text)",
          }}
        >
          {favoriteId ? "저장됨" : "저장"}
        </button>
      </div>

      {saveError ? (
        <p role="alert" className="text-xs" style={{ color: "var(--color-danger)" }}>
          {saveError}
        </p>
      ) : null}
    </div>
  );
}
