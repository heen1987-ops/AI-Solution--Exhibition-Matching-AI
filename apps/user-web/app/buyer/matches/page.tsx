"use client";

/**
 * 바이어 매칭 결과 화면 (WAVE 2C USER-WEB-BUYER).
 *
 * 요구사항 (작업 지시 원문)
 * --------------------------
 * "Matching results screen: match summary, natural-language refine box, hard-filter chips,
 * exhibitor result cards ..., compare-up-to-4 button, save-to-favorites, request-meeting CTA."
 *
 * `event_id`에 대한 메모: 이 저장소에는 아직 "현재 방문 세션의 행사 ID"를 클라이언트에서
 * 조회하는 공용 헬퍼가 없다(7.1절 `CreateSessionResponse`도 이를 되돌려주지 않는다 -
 * `lib/api-client.ts` 참고). 백주대간 행사는 단일 이벤트 전제라 `NEXT_PUBLIC_EVENT_ID`
 * 환경변수로 우선 대체하고, 값이 없으면 자연어 정제만 비활성화한다(핵심 매칭 목록 조회는
 * event_id 없이도 동작하는 프로파일 기반 추천 세션이라 영향 없음). TODO(통합 시 실제 세션
 * 컨텍스트에서 event_id를 읽는 공용 훅이 생기면 이 자리를 교체).
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { ApiClientError, updateProfilePreferences } from "@/lib/api-client";
import type { ProfileView } from "@/lib/types";

import { fetchBuyerProfile } from "@/features/buyer-profile/api";
import type { BuyerVerification } from "@/features/buyer-profile/types";
import VerificationStatusBanner from "@/features/buyer-profile/VerificationStatusBanner";

import {
  buildHardFilterChips,
  buildMatchingCardData,
  fetchMatchingSlate,
  fetchMoreMatchingSlate,
  removeHardFilterPatch,
  type HardFilterChip,
} from "@/features/buyer-matching/api";
import ExhibitorResultCard from "@/features/buyer-matching/ExhibitorResultCard";
import HardFilterChips from "@/features/buyer-matching/HardFilterChips";
import RefineBox from "@/features/buyer-matching/RefineBox";
import type { MatchingCardData } from "@/features/buyer-matching/types";

import { ComparisonSelectionProvider, useComparisonSelection } from "@/features/exhibitor-comparison/comparison-selection";

const EVENT_ID = process.env.NEXT_PUBLIC_EVENT_ID ?? "";

type LoadState = "loading" | "loaded" | "empty" | "error";

function CompareFloatingButton() {
  const { selectedIds } = useComparisonSelection();
  if (selectedIds.length === 0) return null;
  return (
    <Link
      href={`/buyer/compare?ids=${selectedIds.map(encodeURIComponent).join(",")}`}
      className="tap-target fixed bottom-24 right-4 z-30 rounded-full px-4 py-3 text-sm font-bold shadow-lg"
      style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
    >
      비교하기 ({selectedIds.length}/4)
    </Link>
  );
}

function BuyerMatchesContent() {
  const [profile, setProfile] = useState<ProfileView | null>(null);
  const [verification, setVerification] = useState<BuyerVerification | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [cards, setCards] = useState<MatchingCardData[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [filterChips, setFilterChips] = useState<HardFilterChip[]>([]);
  const [removingCode, setRemovingCode] = useState<string | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const loadAll = useCallback(async () => {
    setState("loading");
    setError(null);
    try {
      const [buyerProfile, slate] = await Promise.all([fetchBuyerProfile(), fetchMatchingSlate()]);
      setProfile(buyerProfile.profile);
      setVerification(buyerProfile.verification);
      setFilterChips(buildHardFilterChips(buyerProfile.profile));
      setSessionId(slate.recommendationSessionId);
      setNextCursor(slate.nextCursor);

      const cardData = await Promise.all(slate.items.map((item) => buildMatchingCardData(item)));
      setCards(cardData);
      setState(cardData.length === 0 ? "empty" : "loaded");
    } catch (err) {
      if (err instanceof ApiClientError && err.code === "NO_CANDIDATE") {
        setCards([]);
        setState("empty");
      } else {
        setError(err instanceof ApiClientError ? err.message : "매칭 결과를 불러오지 못했어요.");
        setState("error");
      }
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  async function handleLoadMore() {
    if (!sessionId || !nextCursor) return;
    setLoadingMore(true);
    try {
      const page = await fetchMoreMatchingSlate(sessionId, nextCursor);
      const additional = await Promise.all(page.items.map((item) => buildMatchingCardData(item)));
      setCards((prev) => [...prev, ...additional]);
      setNextCursor(page.nextCursor);
    } catch {
      // 추가 로드 실패는 화면 전체를 막지 않는다 - 이미 보이는 결과는 그대로 둔다.
    } finally {
      setLoadingMore(false);
    }
  }

  async function handleRemoveFilter(chip: HardFilterChip) {
    setRemovingCode(chip.code);
    try {
      await updateProfilePreferences(removeHardFilterPatch(chip));
      setFilterChips((prev) => prev.filter((item) => item.code !== chip.code));
      await loadAll();
    } catch {
      // 실패해도 칩은 그대로 남긴다 - 사용자가 다시 시도할 수 있게.
    } finally {
      setRemovingCode(null);
    }
  }

  function handleApplyRefinement(concepts: string[]) {
    setFilterChips((prev) => {
      const existingCodes = new Set(prev.map((chip) => chip.code));
      const added = concepts
        .filter((code) => !existingCodes.has(code))
        .map<HardFilterChip>((code) => ({ field: "business_interests", code, label: code }));
      return [...prev, ...added];
    });
    void updateProfilePreferences({ business_interests: { add: concepts, remove: [] } })
      .then(() => loadAll())
      .catch(() => {
        // 정제 검색 결과 반영 실패는 조용히 무시한다 - 칩은 이미 화면에 보여줬다.
      });
  }

  return (
    <div className="mx-auto flex max-w-screen-content flex-col gap-4 px-4 py-4">
      <header className="flex flex-col gap-2">
        <h1 className="text-xl font-bold">업체 매칭 결과</h1>
        {verification ? <VerificationStatusBanner verification={verification} /> : null}
        {state === "loaded" ? (
          <p data-testid="match-summary" className="text-sm" style={{ color: "var(--color-text-muted)" }}>
            조건에 맞는 업체 {cards.length}곳을 찾았어요.
          </p>
        ) : null}
      </header>

      {EVENT_ID ? (
        <RefineBox eventId={EVENT_ID} onApply={handleApplyRefinement} />
      ) : (
        <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
          자연어 검색은 현재 준비 중이에요.
        </p>
      )}

      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold" style={{ color: "var(--color-text-muted)" }}>
          적용 중인 조건
        </h2>
        <HardFilterChips chips={filterChips} onRemove={(chip) => void handleRemoveFilter(chip)} removingCode={removingCode} />
      </div>

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
            {error}
          </p>
          <button
            type="button"
            onClick={() => void loadAll()}
            className="tap-target mt-3 rounded-lg border px-4 text-sm font-semibold"
            style={{ borderColor: "var(--color-border)" }}
          >
            다시 시도
          </button>
        </div>
      ) : null}

      {state === "empty" ? (
        <div className="rounded-2xl border p-4" style={{ borderColor: "var(--color-border)" }}>
          <p className="font-semibold">아직 조건에 맞는 업체를 찾지 못했어요.</p>
          <p className="mt-1 text-sm" style={{ color: "var(--color-text-muted)" }}>
            바이어 프로파일에서 조건을 더 알려주시면 추천이 더 정확해져요.
          </p>
          <Link
            href="/buyer/profile"
            className="tap-target mt-3 inline-block rounded-lg px-4 text-sm font-bold"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
          >
            바이어 프로파일 수정
          </Link>
        </div>
      ) : null}

      {state === "loaded" && verification
        ? cards.map((card) => (
            <ExhibitorResultCard
              key={`${card.item.object_type}-${card.item.object_id}-${card.item.rank}`}
              data={card}
              verificationStatus={verification.status}
              recommendationSessionId={sessionId}
            />
          ))
        : null}

      {state === "loaded" && nextCursor ? (
        <button
          type="button"
          onClick={() => void handleLoadMore()}
          disabled={loadingMore}
          className="tap-target w-full rounded-lg border px-4 text-sm font-semibold disabled:opacity-60"
          style={{ borderColor: "var(--color-border)" }}
        >
          {loadingMore ? "불러오는 중" : "더 보기"}
        </button>
      ) : null}

      <CompareFloatingButton />

      {profile ? (
        <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
          프로파일 버전 v{profile.current_version}
        </p>
      ) : null}
    </div>
  );
}

export default function BuyerMatchesPage() {
  return (
    <ComparisonSelectionProvider>
      <BuyerMatchesContent />
    </ComparisonSelectionProvider>
  );
}
