"use client";

/**
 * 추천 카드 (공용 재사용 컴포넌트) - U-08 행동 중심 추천 홈, U-09 추천 전체에서 쓴다.
 *
 * 근거 문서
 * ---------
 * - docs/user-ia-wireframes.md 7절 U-08/U-09 와이어프레임 - "A양조장 · 조건이 잘 맞아요 /
 *   드라이한 증류주 · 선물용 / 도보 3분 · 대기 약 5분 / [상세] [저장] [방문하기]" 카드
 *   레이아웃의 1차 근거.
 * - 10절(추천 설명) - 권장 문구("조건이 잘 맞아요" 류)만 쓰고, 지양 문구(내부 점수·
 *   "AI가 분석한", "98.7% 일치", 성별/연령 추정, 근거 없는 가격·재고)는 쓰지 않는다.
 *   `match_level`(VERY_HIGH~LOW)은 숫자·퍼센트 대신 이 컴포넌트 안에서 정성적 문구로만
 *   변환한다.
 * - 9절 U-09 "추천 인상 이벤트는 카드가 실제 뷰포트에 노출된 경우에만 ... 기록한다" -
 *   IntersectionObserver로 50% 이상 노출 시 1회만 `RECOMMENDATION_IMPRESSION`을 기록한다.
 * - 9.1절(공통 컴포넌트) "모든 데이터 카드에는 loading, loaded, empty, stale, error,
 *   offline 상태를 정의한다" - 이 카드는 개별 카드 단위로 loading/loaded/error/stale을
 *   다루고(empty는 목록 단위라 호출부 책임), `data-state` 속성으로 노출한다.
 * - frontend/lib/types.ts의 `RecommendationItem`은 업체·부스·제품 "이름"을 포함하지
 *   않는다(9.1절 예시 JSON에도 없음). 이 카드는 `object_type`/`object_id`로
 *   `getBooth`/`getProduct`(frontend/lib/api-client.ts)를 직접 호출해 표시용 이름·상태를
 *   보강한다. `EXHIBITOR`/`PROGRAM`은 공개 상세 조회 함수가 아직 없어(TODO 아래 참고)
 *   객체 ID 기반 임시 문구로 대체한다.
 * - 12.1/12.2절 행동 이벤트 이름 규칙 - `recommendation_impression`, `recommendation_saved`
 *   을 `postInteraction`으로 기록한다(분석 이벤트 실패가 화면 동작을 막지 않도록
 *   fire-and-forget).
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import {
  ApiClientError,
  createFavorite,
  deleteFavorite,
  getBooth,
  getProduct,
  postInteraction,
} from "@/lib/api-client";
import type {
  MatchLevel,
  RecommendableObjectType,
  RecommendationItem,
} from "@/lib/types";

import OperatingStatusBadge, {
  boothOperatingStatusToCode,
  type OperatingStatusCode,
} from "@/components/OperatingStatusBadge";

type PrimaryAction =
  | { kind: "link"; label: string; href: string }
  | { kind: "button"; label: string; onClick: () => void; disabled: boolean };

// 10절 권장 표현: 내부 점수 대신 정성적 문구만 노출한다.
const MATCH_LEVEL_PHRASE: Record<MatchLevel, string> = {
  VERY_HIGH: "조건이 매우 잘 맞아요",
  HIGH: "조건이 잘 맞아요",
  MEDIUM: "조건이 어느 정도 맞아요",
  LOW: "조건과 일부만 맞아요",
};

const OBJECT_TYPE_LABEL: Record<RecommendableObjectType, string> = {
  BOOTH: "부스",
  PRODUCT: "제품",
  EXHIBITOR: "업체",
  PROGRAM: "프로그램",
};

/** 9.2절 표에 없는 "혼잡" 판정 임계값. 정확한 기준은 아직 설계되지 않아 합리적 기본값을
 * 쓴다. TODO(현장 운영 정책 확정 후 대조): 부스·구역별로 달라질 수 있다. */
const CROWDED_WAIT_MINUTES_THRESHOLD = 15;

interface ResolvedDetail {
  title: string;
  subtitle: string | null;
  detailHref: string | null;
  boothOperatingStatusCode?: OperatingStatusCode;
  statusObservedAt?: string | null;
}

type ResolveState = "loading" | "loaded" | "error";

function formatMeta(item: RecommendationItem): string | null {
  const parts: string[] = [];
  if (item.estimated_walk_minutes != null) {
    parts.push(`도보 ${item.estimated_walk_minutes}분`);
  } else if (item.distance_meters != null) {
    parts.push(`${item.distance_meters}m`);
  }
  if (item.estimated_wait_minutes != null) {
    parts.push(`대기 약 ${item.estimated_wait_minutes}분`);
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

function recommendedActionLabel(item: RecommendationItem): string {
  switch (item.recommended_action) {
    case "VISIT_NOW":
      return "방문하기";
    case "REQUEST_MEETING":
      return "상담 요청";
    case "ADD_TO_ROUTE":
      return "경로에 추가";
    case "VIEW_DETAILS":
      return "상세 보기";
    default:
      // RecommendedAction은 OpenEnum이라 문서에 없는 코드가 올 수 있다.
      return "자세히 보기";
  }
}

export interface RecommendationCardProps {
  item: RecommendationItem;
  /** 현재 카드가 속한 추천 실행 ID. 행동 이벤트 공통 속성(12.2절)에 포함한다. */
  recommendationSessionId?: string | null;
  /** 16.2절 화면 코드. 행동 이벤트의 발생 위치를 남긴다. */
  screen?: "HOME" | "EXPLORE" | "MAP" | "SCHEDULE" | "MY";
  /** 상위(`RecommendationResponse.stale`)가 오래된 추천임을 알리고 싶을 때. */
  stale?: boolean;
  /** 이미 저장된 항목이면 초기 즐겨찾기 ID를 넘겨 카드가 다시 조회하지 않게 한다. */
  initialFavoriteId?: string | null;
  onSaveChange?: (saved: boolean, favoriteId: string | null) => void;
  className?: string;
}

export default function RecommendationCard({
  item,
  recommendationSessionId,
  screen,
  stale = false,
  initialFavoriteId = null,
  onSaveChange,
  className,
}: RecommendationCardProps) {
  const [resolved, setResolved] = useState<ResolvedDetail | null>(null);
  const [resolveState, setResolveState] = useState<ResolveState>("loading");
  const [favoriteId, setFavoriteId] = useState<string | null>(initialFavoriteId);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [routeAdded, setRouteAdded] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  const cardRef = useRef<HTMLDivElement | null>(null);
  const impressionFiredRef = useRef(false);

  // 표시용 이름·운영상태 보강. RecommendationItem은 이름을 담지 않는다(위 주석 참고).
  useEffect(() => {
    let cancelled = false;

    async function resolve() {
      setResolveState("loading");
      try {
        if (item.object_type === "BOOTH") {
          const booth = await getBooth(item.object_id, {
            matchResultId: item.match_result_id ?? undefined,
          });
          if (cancelled) return;
          const query = item.match_result_id
            ? `?matchResultId=${encodeURIComponent(item.match_result_id)}`
            : "";
          setResolved({
            title: booth.exhibitor.name,
            subtitle: booth.exhibitor.summary ?? `부스 ${booth.booth_number}`,
            detailHref: `/booths/${encodeURIComponent(booth.booth_id)}${query}`,
            boothOperatingStatusCode: boothOperatingStatusToCode(booth.operating_status),
            statusObservedAt: booth.status_observed_at,
          });
        } else if (item.object_type === "PRODUCT") {
          const product = await getProduct(item.object_id);
          if (cancelled) return;
          setResolved({
            title: product.product_name,
            subtitle: [product.exhibitor.name, product.category].filter(Boolean).join(" · "),
            detailHref: `/products/${encodeURIComponent(product.product_id)}`,
            statusObservedAt: product.data_observed_at,
          });
        } else {
          // TODO(전시정보 API 확장 후 대조): EXHIBITOR/PROGRAM 공개 상세 조회 엔드포인트가
          // 아직 frontend/lib/api-client.ts에 없다(현재는 booths/products만 있다). 이름을
          // 확인할 방법이 없으므로 대상 유형만 알리고 상세 링크는 제공하지 않는다.
          if (cancelled) return;
          setResolved({
            title: item.object_type === "EXHIBITOR" ? "업체 정보" : "프로그램 정보",
            subtitle: null,
            detailHref: null,
          });
        }
        if (!cancelled) setResolveState("loaded");
      } catch {
        if (!cancelled) setResolveState("error");
      }
    }

    void resolve();
    return () => {
      cancelled = true;
    };
  }, [item.object_type, item.object_id, item.match_result_id]);

  // 9절: 카드가 실제 뷰포트에 절반 이상 보였을 때 1회만 노출 이벤트를 기록한다.
  useEffect(() => {
    const node = cardRef.current;
    if (!node || impressionFiredRef.current) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (!entry || impressionFiredRef.current) return;
        if (entry.isIntersecting && entry.intersectionRatio >= 0.5) {
          impressionFiredRef.current = true;
          void postInteraction({
            event_type: "RECOMMENDATION_IMPRESSION",
            object_type: item.object_type,
            object_id: item.object_id,
            recommendation_session_id: recommendationSessionId ?? null,
            match_result_id: item.match_result_id,
            rank_at_event: item.rank,
            screen: screen ?? null,
            occurred_at: new Date().toISOString(),
          }).catch(() => {
            // 분석 이벤트 실패는 화면 동작을 막지 않는다.
          });
          observer.disconnect();
        }
      },
      { threshold: [0.5] },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [item.object_id, item.object_type, item.match_result_id, item.rank, recommendationSessionId, screen]);

  function recordOpened() {
    void postInteraction({
      event_type: "RECOMMENDATION_OPENED",
      object_type: item.object_type,
      object_id: item.object_id,
      recommendation_session_id: recommendationSessionId ?? null,
      match_result_id: item.match_result_id,
      rank_at_event: item.rank,
      screen: screen ?? null,
      occurred_at: new Date().toISOString(),
    }).catch(() => {});
  }

  async function handleToggleSave() {
    if (saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      if (favoriteId) {
        await deleteFavorite(favoriteId);
        setFavoriteId(null);
        onSaveChange?.(false, null);
      } else {
        const favorite = await createFavorite({
          object_type: item.object_type,
          object_id: item.object_id,
          source: "RECOMMENDATION",
          match_result_id: item.match_result_id,
        });
        setFavoriteId(favorite.favorite_id);
        onSaveChange?.(true, favorite.favorite_id);
        void postInteraction({
          event_type: "RECOMMENDATION_SAVED",
          object_type: item.object_type,
          object_id: item.object_id,
          recommendation_session_id: recommendationSessionId ?? null,
          match_result_id: item.match_result_id,
          rank_at_event: item.rank,
          screen: screen ?? null,
          occurred_at: new Date().toISOString(),
        }).catch(() => {});
      }
    } catch (err) {
      setSaveError(err instanceof ApiClientError ? err.message : "저장하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  }

  function handleAddToRoute() {
    setRouteAdded(true);
    void postInteraction({
      event_type: "ROUTE_ITEM_ADDED",
      object_type: item.object_type,
      object_id: item.object_id,
      recommendation_session_id: recommendationSessionId ?? null,
      match_result_id: item.match_result_id,
      rank_at_event: item.rank,
      screen: screen ?? null,
      occurred_at: new Date().toISOString(),
    }).catch(() => {});
    // TODO(U-13 지도·추천 경로 구현 후 대조): 실제 경로 생성은 `createRoute`(경로 시작점·
    // 전체 대상 목록이 필요)가 담당한다. 이 카드는 "경로에 추가" 의도를 기록만 하고,
    // 실제 경로 조립은 U-13 화면에서 이 인터랙션 로그를 참고해 처리한다.
  }

  function handleDismiss() {
    setDismissed(true);
    void postInteraction({
      event_type: "RECOMMENDATION_DISMISSED",
      object_type: item.object_type,
      object_id: item.object_id,
      recommendation_session_id: recommendationSessionId ?? null,
      match_result_id: item.match_result_id,
      rank_at_event: item.rank,
      screen: screen ?? null,
      occurred_at: new Date().toISOString(),
    }).catch(() => {
      // 학습 이벤트 실패가 목록 탐색 자체를 막지는 않는다.
    });
  }

  const meta = formatMeta(item);
  const reasons = item.reasons.slice(0, 3);
  const showCrowded =
    item.estimated_wait_minutes != null &&
    item.estimated_wait_minutes >= CROWDED_WAIT_MINUTES_THRESHOLD;

  const primaryAction: PrimaryAction | null = (() => {
    if (item.recommended_action === "VIEW_DETAILS") return null; // 상세 버튼과 중복
    if (item.recommended_action === "REQUEST_MEETING") {
      if (!item.exhibitor_id) return null;
      return {
        kind: "link",
        label: recommendedActionLabel(item),
        href: `/meetings/new?exhibitorId=${encodeURIComponent(item.exhibitor_id)}`,
      };
    }
    if (item.recommended_action === "ADD_TO_ROUTE") {
      return {
        kind: "button",
        label: routeAdded ? "경로에 추가됨" : recommendedActionLabel(item),
        onClick: handleAddToRoute,
        disabled: routeAdded,
      };
    }
    // VISIT_NOW 및 그 외 개방형 코드는 상세 화면으로 보낸다(방문 관련 행동은 상세에서 처리).
    if (resolved?.detailHref) {
      return {
        kind: "link",
        label: recommendedActionLabel(item),
        href: resolved.detailHref,
      };
    }
    return null;
  })();

  if (dismissed) {
    return (
      <div
        role="status"
        className={`rounded-2xl border p-4 text-sm ${className ?? ""}`}
        style={{ borderColor: "var(--color-border)", color: "var(--color-text-muted)" }}
      >
        관심 없음으로 반영했습니다. 다음 추천을 확인해 주세요.
      </div>
    );
  }

  return (
    <div
      ref={cardRef}
      data-state={resolveState}
      className={`recommendation-card border p-4 ${className ?? ""}`}
      style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
    >
      {stale ? (
        <p className="mb-2 text-xs" style={{ color: "var(--color-text-muted)" }}>
          최신 정보가 아닐 수 있어요. 새로고침하면 최신 추천을 볼 수 있어요.
        </p>
      ) : null}

      <span className="recommendation-rank" aria-label={`추천 순위 ${item.rank}위`}>
        <span aria-hidden="true">MATCH</span>
        <strong>{String(item.rank).padStart(2, "0")}</strong>
      </span>

      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          {resolveState === "loading" ? (
            <div className="space-y-2" aria-hidden="true">
              <div className="h-5 w-2/3 rounded" style={{ backgroundColor: "var(--color-border)" }} />
              <div className="h-4 w-1/2 rounded" style={{ backgroundColor: "var(--color-border)" }} />
            </div>
          ) : resolveState === "error" ? (
            <p className="text-sm font-semibold" style={{ color: "var(--color-danger)" }}>
              정보를 불러오지 못했어요.
            </p>
          ) : (
            <>
              <p className="truncate text-base font-bold">{resolved?.title}</p>
              <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
                {MATCH_LEVEL_PHRASE[item.match_level]}
              </p>
            </>
          )}
        </div>
        <span
          className="shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold"
          style={{ backgroundColor: "var(--color-bg)", color: "var(--color-text-muted)", border: "1px solid var(--color-border)" }}
        >
          {OBJECT_TYPE_LABEL[item.object_type]}
        </span>
      </div>

      {resolveState === "loaded" && resolved?.subtitle ? (
        <p className="mt-1 text-sm" style={{ color: "var(--color-text-muted)" }}>
          {resolved.subtitle}
        </p>
      ) : null}

      {reasons.length > 0 ? (
        <ul className="recommendation-reasons mt-3 space-y-0.5">
          {reasons.map((reason) => (
            <li key={`${reason.code}-${reason.text}`} className="text-sm">
              · {reason.text}
            </li>
          ))}
        </ul>
      ) : null}

      {meta ? (
        <p className="mt-2 text-sm" style={{ color: "var(--color-text-muted)" }}>
          {meta}
        </p>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-1.5">
        {resolved?.boothOperatingStatusCode ? (
          <OperatingStatusBadge
            code={resolved.boothOperatingStatusCode}
            observedAt={resolved.statusObservedAt}
            showObservedTime
            size="sm"
          />
        ) : null}
        {item.availability.tasting ? <OperatingStatusBadge code="TASTING_AVAILABLE" size="sm" /> : null}
        {item.availability.purchase ? <OperatingStatusBadge code="PURCHASE_AVAILABLE" size="sm" /> : null}
        {item.availability.meeting ? <OperatingStatusBadge code="MEETING_AVAILABLE" size="sm" /> : null}
        {showCrowded ? <OperatingStatusBadge code="CROWDED" size="sm" /> : null}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {resolved?.detailHref ? (
          <Link
            href={resolved.detailHref}
            onClick={recordOpened}
            className="tap-target rounded-lg border px-3 text-sm font-semibold"
            style={{ borderColor: "var(--color-border)" }}
          >
            상세
          </Link>
        ) : null}

        <button
          type="button"
          onClick={handleToggleSave}
          disabled={saving}
          aria-pressed={Boolean(favoriteId)}
          className="tap-target rounded-lg border px-3 text-sm font-semibold disabled:opacity-60"
          style={{
            borderColor: favoriteId ? "var(--color-brand)" : "var(--color-border)",
            color: favoriteId ? "var(--color-brand)" : "var(--color-text)",
          }}
        >
          {favoriteId ? "저장됨" : "저장"}
        </button>

        <button
          type="button"
          onClick={handleDismiss}
          className="tap-target rounded-lg border px-3 text-sm font-semibold"
          style={{ borderColor: "var(--color-border)", color: "var(--color-text-muted)" }}
        >
          관심 없음
        </button>

        {primaryAction ? (
          primaryAction.kind === "link" ? (
            <Link
              href={primaryAction.href}
              onClick={recordOpened}
              className="tap-target rounded-full px-4 text-sm font-bold"
              style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
            >
              {primaryAction.label}
            </Link>
          ) : (
            <button
              type="button"
              onClick={primaryAction.onClick}
              disabled={primaryAction.disabled}
              className="tap-target rounded-full px-4 text-sm font-bold disabled:opacity-60"
              style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
            >
              {primaryAction.label}
            </button>
          )
        ) : null}
      </div>

      {saveError ? (
        <p role="alert" className="mt-2 text-xs" style={{ color: "var(--color-danger)" }}>
          {saveError}
        </p>
      ) : null}
    </div>
  );
}
