"use client";

/**
 * U-11 제품 상세.
 *
 * 근거 문서
 * ---------
 * - docs/user-ia-wireframes.md 5.1절: 경로 `/products/{productId}`, 진입 조건 "없음",
 *   핵심 API `GET /products/{id}` - `frontend/lib/api-client.ts`의 `getProduct`를 그대로
 *   쓴다.
 * - 7절 U-11 필수 영역: "제품·업체·이미지 / 주종, 도수, 원료, 맛·향, 용량, 가격 / 시음·
 *   구매·택배 가능 여부 / 정보 갱신시각과 업체 확인 여부 / 부스 방문, 유사 제품, 저장"의
 *   1차 근거. "가격·재고가 제공되지 않은 경우 빈 값을 `문의` 또는 `정보 없음`으로
 *   명시한다"는 `ProductDetailResponse.price_display_status`(AVAILABLE/INQUIRY/UNKNOWN)로
 *   그대로 구현한다.
 * - `ProductDetailResponse`(frontend/lib/types.ts)에는 이미지 URL 필드가 없어 이미지를
 *   지어내지 않고 플레이스홀더로 대체한다(부스 상세와 동일한 근거).
 * - `taste`/`aroma`는 08 문서 5.2절 패턴대로 `{개념코드: 0~5 강도}`다. 6단계 온톨로지
 *   문서가 아직 없어 개념코드를 한글 라벨로 바꿔 부르지 않고(임의 매핑 금지), 코드값과
 *   강도 막대만 보여준다. TODO(온톨로지 코드→표시 라벨 매핑 API가 생기면 대조해 교체).
 * - "유사 제품"(`similar_product_ids`)은 이름이 없는 ID 배열이라, 각 ID를 `getProduct`로
 *   개별 조회해 이름을 보강한다(부스·제품 이름이 추천 응답에 없는 것과 같은 제약,
 *   `components/RecommendationCard.tsx` 주석 참고).
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ApiClientError, createFavorite, deleteFavorite, getProduct } from "@/lib/api-client";
import type { ProductDetailResponse } from "@/lib/types";

import OperatingStatusBadge from "@/components/OperatingStatusBadge";

type LoadState = "loading" | "loaded" | "error";

function formatPrice(product: ProductDetailResponse): string {
  if (product.price_display_status === "INQUIRY") return "문의";
  if (product.price_display_status === "UNKNOWN" || !product.price) return "정보 없음";
  const formatter = new Intl.NumberFormat("ko-KR");
  const { min_amount, max_amount, currency } = product.price;
  if (min_amount != null && max_amount != null && min_amount !== max_amount) {
    return `${formatter.format(min_amount)}~${formatter.format(max_amount)} ${currency}`;
  }
  const amount = min_amount ?? max_amount;
  return amount != null ? `${formatter.format(amount)} ${currency}` : "정보 없음";
}

function formatObservedAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("ko-KR", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function IntensityBars({ label, values }: { label: string; values: Record<string, number> }) {
  const entries = Object.entries(values);
  if (entries.length === 0) return null;
  return (
    <div>
      <p className="text-sm font-semibold" style={{ color: "var(--color-text-muted)" }}>
        {label}
      </p>
      <ul className="mt-1 space-y-1">
        {entries.map(([code, value]) => (
          <li key={code} className="flex items-center gap-2 text-sm">
            {/* 6단계 온톨로지 라벨 매핑이 아직 없어 코드값을 그대로 보여준다(위 주석 참고). */}
            <span className="w-28 shrink-0 truncate" title={code}>
              {code}
            </span>
            <span className="flex flex-1 gap-0.5" aria-hidden="true">
              {[0, 1, 2, 3, 4].map((step) => (
                <span
                  key={step}
                  className="h-2 flex-1 rounded-full"
                  style={{
                    backgroundColor: step < value ? "var(--color-brand)" : "var(--color-border)",
                  }}
                />
              ))}
            </span>
            <span className="sr-only">5점 만점 중 {value}점</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SimilarProductLink({ productId }: { productId: string }) {
  const [name, setName] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getProduct(productId)
      .then((product) => {
        if (!cancelled) setName(product.product_name);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [productId]);

  return (
    <Link
      href={`/products/${encodeURIComponent(productId)}`}
      className="tap-target inline-flex rounded-lg border px-3 text-sm font-semibold"
      style={{ borderColor: "var(--color-border)" }}
    >
      {failed ? "제품 보기" : (name ?? "불러오는 중…")}
    </Link>
  );
}

export default function ProductDetailPage() {
  const params = useParams<{ productId: string }>();

  const [product, setProduct] = useState<ProductDetailResponse | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<ApiClientError | null>(null);

  const [favoriteId, setFavoriteId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setState("loading");
    setError(null);
    try {
      const response = await getProduct(params.productId);
      setProduct(response);
      setState("loaded");
    } catch (err) {
      setError(err instanceof ApiClientError ? err : null);
      setState("error");
    }
  }, [params.productId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleToggleSave() {
    if (!product || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      if (favoriteId) {
        await deleteFavorite(favoriteId);
        setFavoriteId(null);
      } else {
        const favorite = await createFavorite({
          object_type: "PRODUCT",
          object_id: product.product_id,
          source: "SEARCH",
        });
        setFavoriteId(favorite.favorite_id);
      }
    } catch (err) {
      setSaveError(err instanceof ApiClientError ? err.message : "저장하지 못했습니다.");
    } finally {
      setSaving(false);
    }
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

  if (state === "error" || !product) {
    return (
      <div className="mx-auto max-w-screen-content px-4 py-4">
        <div role="alert" className="rounded-2xl border p-4" style={{ borderColor: "var(--color-border)" }}>
          <p className="font-semibold" style={{ color: "var(--color-danger)" }}>
            {error?.code === "NETWORK_ERROR"
              ? "서버에 연결할 수 없어요. 네트워크 상태를 확인해 주세요."
              : (error?.message ?? "제품 정보를 불러오지 못했어요.")}
          </p>
          <button
            type="button"
            onClick={() => void load()}
            className="tap-target mt-3 rounded-lg border px-4 text-sm font-semibold"
            style={{ borderColor: "var(--color-border)" }}
          >
            다시 시도
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-screen-content space-y-4 px-4 py-4">
      {/* ProductDetailResponse에 이미지 필드가 없어 자리표시자로 대체한다(위 주석 참고). */}
      <div
        className="flex h-32 items-center justify-center rounded-2xl text-sm"
        style={{ backgroundColor: "var(--color-bg)", color: "var(--color-text-muted)", border: "1px dashed var(--color-border)" }}
      >
        이미지 준비 중
      </div>

      <div>
        <h1 className="text-xl font-bold">{product.product_name}</h1>
        <p className="mt-1 text-sm" style={{ color: "var(--color-text-muted)" }}>
          {product.exhibitor.name}
          {product.category ? ` · ${product.category}` : ""}
        </p>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div>
          <dt style={{ color: "var(--color-text-muted)" }}>도수</dt>
          <dd>{product.alcohol_percentage != null ? `${product.alcohol_percentage}%` : "정보 없음"}</dd>
        </div>
        <div>
          <dt style={{ color: "var(--color-text-muted)" }}>용량</dt>
          <dd>{product.volume_ml != null ? `${product.volume_ml}ml` : "정보 없음"}</dd>
        </div>
        <div>
          <dt style={{ color: "var(--color-text-muted)" }}>가격</dt>
          <dd>{formatPrice(product)}</dd>
        </div>
        <div>
          <dt style={{ color: "var(--color-text-muted)" }}>원료</dt>
          <dd>{product.main_ingredients.length > 0 ? product.main_ingredients.join(", ") : "정보 없음"}</dd>
        </div>
      </dl>

      {product.taste ? <IntensityBars label="맛" values={product.taste} /> : null}
      {product.aroma ? <IntensityBars label="향" values={product.aroma} /> : null}

      <section aria-labelledby="availability-heading" className="space-y-2">
        <h2 id="availability-heading" className="text-sm font-bold" style={{ color: "var(--color-text-muted)" }}>
          현재 가능한 방법
        </h2>
        <div className="flex flex-wrap gap-1.5">
          {product.availability.tasting ? <OperatingStatusBadge code="TASTING_AVAILABLE" /> : null}
          {product.availability.purchase ? <OperatingStatusBadge code="PURCHASE_AVAILABLE" /> : null}
          {product.availability.delivery ? (
            <span
              className="inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold"
              style={{ backgroundColor: "var(--color-bg)", border: "1px solid var(--color-border)" }}
            >
              택배 가능
            </span>
          ) : null}
          {!product.availability.tasting && !product.availability.purchase && !product.availability.delivery ? (
            <OperatingStatusBadge code="UNKNOWN" />
          ) : null}
        </div>
      </section>

      <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
        {formatObservedAt(product.data_observed_at)} 기준
        {product.verified_by_exhibitor ? " · 업체 확인 완료" : " · 업체 확인 대기 중"}
      </p>

      <div className="flex flex-wrap gap-2">
        {product.booth_id ? (
          <Link
            href={`/booths/${encodeURIComponent(product.booth_id)}`}
            className="tap-target rounded-lg px-4 text-sm font-bold"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
          >
            부스 방문하기
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

      {product.similar_product_ids.length > 0 ? (
        <section aria-labelledby="similar-heading" className="space-y-2">
          <h2 id="similar-heading" className="text-sm font-bold" style={{ color: "var(--color-text-muted)" }}>
            유사 제품
          </h2>
          <div className="flex flex-wrap gap-2">
            {product.similar_product_ids.map((id) => (
              <SimilarProductLink key={id} productId={id} />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
