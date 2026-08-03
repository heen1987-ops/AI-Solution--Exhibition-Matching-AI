"use client";

/**
 * U-05 관람객 취향 화면.
 *
 * 근거: docs/user-ia-wireframes.md 7절 "U-05 관람객 취향" - "4개의 짧은 카드"(주종, 맛·향,
 * 도수, 가격), "모든 질문은 건너뛰기와 `잘 모르겠음`을 제공하며, 선택 즉시 저장한다".
 * API: 인터페이스 명세 8.2절 `PUT /api/v1/profiles/me/consumer-preferences`
 * (`postAnswers({step:"CONSUMER_PREFERENCES"})`).
 *
 * 주종·맛·향은 PUBLISHED 온톨로지의 assignable concept를 사용한다. 도수·가격은 화면
 * 구간을 API 범위값으로 변환한다.
 */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiClientError, postAnswers, postInteraction } from "@/lib/api-client";
import { PRODUCT_CATEGORY_OPTIONS, TASTE_OPTIONS } from "@/lib/profile-options";
import type { AlcoholPercentageRange, PriceRange, PurchaseIntent } from "@/lib/types";
import { loadOnboardingState, saveOnboardingState } from "@/lib/onboarding-state";

import ChoiceChip from "../_components/ChoiceChip";
import OnboardingShell from "../_components/OnboardingShell";

const UNKNOWN = "UNKNOWN" as const;

type AlcoholOption = "LOW" | "MID" | "HIGH" | "ANY";
const ALCOHOL_OPTIONS: { code: AlcoholOption; label: string; range: AlcoholPercentageRange | null }[] = [
  { code: "LOW", label: "낮음", range: { min: 0, max: 12 } },
  { code: "MID", label: "중간", range: { min: 12, max: 25 } },
  { code: "HIGH", label: "높음", range: { min: 25, max: 60 } },
  { code: "ANY", label: "상관없음", range: null },
];

type PriceOption = "UNDER_20K" | "20_50K" | "50_100K" | "QUALITY_FIRST" | "NO_PLAN";
const PRICE_OPTIONS: {
  code: PriceOption;
  label: string;
  range: PriceRange | null;
  intent: PurchaseIntent;
}[] = [
  { code: "UNDER_20K", label: "2만 원 이하", range: { min_amount: 0, max_amount: 20000, currency: "KRW" }, intent: "LIKELY" },
  { code: "20_50K", label: "2~5만 원", range: { min_amount: 20000, max_amount: 50000, currency: "KRW" }, intent: "LIKELY" },
  { code: "50_100K", label: "5~10만 원", range: { min_amount: 50000, max_amount: 100000, currency: "KRW" }, intent: "LIKELY" },
  { code: "QUALITY_FIRST", label: "품질 우선", range: null, intent: "LIKELY" },
  { code: "NO_PLAN", label: "구매 계획 없음", range: null, intent: "UNLIKELY" },
];

// U-04에서 고른 방문 목적을 공개 BOOTH_SERVICE 코드로 투영한다.
const GOAL_TO_ACTIVITY: Record<string, string> = {
  "GOAL.TASTING": "SERVICE.TASTING",
  "GOAL.ON_SITE_PURCHASE": "SERVICE.PURCHASE",
};

function friendlyErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError) return error.message;
  return "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
}

export default function TastePage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [preferredActivities, setPreferredActivities] = useState<string[]>([]);

  const [categories, setCategories] = useState<string[]>([]);
  const [categoryUnknown, setCategoryUnknown] = useState(false);
  const [tastes, setTastes] = useState<string[]>([]);
  const [tasteUnknown, setTasteUnknown] = useState(false);
  const [alcohol, setAlcohol] = useState<AlcoholOption | null>(null);
  const [price, setPrice] = useState<PriceOption | null>(null);

  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [navBusy, setNavBusy] = useState<"skip" | "next" | "none">("none");

  const skipInitialSave = useRef(true);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const state = loadOnboardingState();
    if (!state.guestSessionId) {
      router.replace("/start");
      return;
    }
    if (state.userType !== "GENERAL_VISITOR") {
      router.replace(state.userType === "BUYER" ? "/onboarding/buyer-needs" : "/onboarding/role");
      return;
    }
    setPreferredActivities(
      state.goals.map((goal) => GOAL_TO_ACTIVITY[goal.code]).filter((value): value is string => Boolean(value)),
    );
    setReady(true);
  }, [router]);

  function buildPayload() {
    const alcoholOption = ALCOHOL_OPTIONS.find((option) => option.code === alcohol) ?? null;
    const priceOption = PRICE_OPTIONS.find((option) => option.code === price) ?? null;
    // TODO(정책 확정 전 잠정 규칙): 주종·맛향을 모두 "잘 모르겠음"으로 남기면 전체 응답을
    // UNKNOWN으로 표시한다. 도수·가격은 "상관없음"/"구매 계획 없음"도 명시적 응답으로 본다.
    const certainty = categoryUnknown && tasteUnknown ? UNKNOWN : "KNOWN";
    return {
      product_categories: categoryUnknown ? [] : categories,
      taste_preferences: tasteUnknown ? [] : tastes,
      alcohol_percentage: alcoholOption?.range ?? null,
      price: priceOption?.range ?? null,
      purchase_intent: priceOption?.intent ?? null,
      preferred_activities: preferredActivities,
      preference_certainty: certainty as "KNOWN" | "UNKNOWN",
    };
  }

  async function persist() {
    setSaveState("saving");
    setErrorMessage(null);
    try {
      const response = await postAnswers({ step: "CONSUMER_PREFERENCES", data: buildPayload() });
      saveOnboardingState({ profileVersion: response.profile_version, minimumProfileCompleted: true });
      setSaveState("saved");
    } catch (error) {
      setSaveState("error");
      setErrorMessage(friendlyErrorMessage(error));
    }
  }

  // 선택 즉시 저장(7절 U-05 설명) - 과도한 요청을 피하기 위해 짧게 debounce한다.
  useEffect(() => {
    if (!ready) return;
    if (skipInitialSave.current) {
      skipInitialSave.current = false;
      return;
    }
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      void persist();
    }, 400);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, categories, categoryUnknown, tastes, tasteUnknown, alcohol, price]);

  function toggleCategory(code: string) {
    setCategoryUnknown(false);
    setCategories((prev) => (prev.includes(code) ? prev.filter((item) => item !== code) : [...prev, code]));
  }

  function toggleCategoryUnknown() {
    setCategoryUnknown((prev) => !prev);
    setCategories([]);
  }

  function toggleTaste(code: string) {
    setTasteUnknown(false);
    setTastes((prev) => (prev.includes(code) ? prev.filter((item) => item !== code) : [...prev, code]));
  }

  function toggleTasteUnknown() {
    setTasteUnknown((prev) => !prev);
    setTastes([]);
  }

  async function handleSkip() {
    setNavBusy("skip");
    void postInteraction({
      event_type: "PROFILE_QUESTION_SKIPPED",
      screen: "ONBOARDING_TASTE",
      occurred_at: new Date().toISOString(),
      context: { question: "consumer_preferences" },
    }).catch(() => undefined);
    router.push("/onboarding/visit-plan");
  }

  async function handleNext() {
    setNavBusy("next");
    if (saveTimer.current) clearTimeout(saveTimer.current);
    await persist();
    setNavBusy("none");
    router.push("/onboarding/visit-plan");
  }

  if (!ready) return null;

  return (
    <OnboardingShell title="어떤 술과 취향을 좋아하세요?" stepLabel="4 / 5">
      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-bold">주종</h2>
        <div className="flex flex-wrap gap-2">
          {PRODUCT_CATEGORY_OPTIONS.map((option) => (
            <ChoiceChip
              key={option.code}
              label={option.label}
              selected={categories.includes(option.code)}
              onClick={() => toggleCategory(option.code)}
            />
          ))}
          <ChoiceChip label="잘 모르겠음" selected={categoryUnknown} onClick={toggleCategoryUnknown} />
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-bold">맛·향</h2>
        <div className="flex flex-wrap gap-2">
          {TASTE_OPTIONS.map((option) => (
            <ChoiceChip
              key={option.code}
              label={option.label}
              selected={tastes.includes(option.code)}
              onClick={() => toggleTaste(option.code)}
            />
          ))}
          <ChoiceChip label="잘 모르겠음" selected={tasteUnknown} onClick={toggleTasteUnknown} />
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-bold">도수</h2>
        <div className="flex flex-wrap gap-2">
          {ALCOHOL_OPTIONS.map((option) => (
            <ChoiceChip
              key={option.code}
              label={option.label}
              selected={alcohol === option.code}
              onClick={() => setAlcohol(option.code)}
            />
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-bold">가격</h2>
        <div className="flex flex-wrap gap-2">
          {PRICE_OPTIONS.map((option) => (
            <ChoiceChip
              key={option.code}
              label={option.label}
              selected={price === option.code}
              onClick={() => setPrice(option.code)}
            />
          ))}
        </div>
      </div>

      <p className="text-xs" style={{ color: "var(--color-text-muted)" }} role="status" aria-live="polite">
        {saveState === "saving" ? "저장하는 중…" : null}
        {saveState === "saved" ? "저장됐어요." : null}
        {saveState === "error" ? errorMessage : null}
      </p>

      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={handleSkip}
          disabled={navBusy !== "none"}
          className="tap-target rounded-lg px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
          style={{ color: "var(--color-text-muted)" }}
        >
          건너뛰기
        </button>
        <button
          type="button"
          onClick={handleNext}
          disabled={navBusy !== "none"}
          className="tap-target flex-1 rounded-xl px-4 py-3 text-base font-bold disabled:cursor-not-allowed disabled:opacity-60"
          style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
        >
          {navBusy === "next" ? "저장하는 중…" : "다음"}
        </button>
      </div>
    </OnboardingShell>
  );
}
